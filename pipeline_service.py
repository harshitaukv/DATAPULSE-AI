"""Pipeline execution: Extract -> Validate -> Transform -> Quality -> Load.

The service owns the full lifecycle of a run: it creates the run record,
executes the stages through the workflow engine (with retries for transient
errors), evaluates quality rules and anomaly detection, writes encrypted
outputs, opens incidents, records automatic recovery actions, validates
outputs, and persists everything. Dashboard numbers are derived from these
records only.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import Dataset, Pipeline, PipelineRun, User
from app.ingestion.loader import load_dataframe
from app.monitoring import anomaly_detector, rules
from app.monitoring.baseline import Baseline, compute_baseline
from app.monitoring.metrics import compute_quality_metrics, feature_vector
from app.processing.cleaner import clean_dataframe
from app.processing.errors import IncompleteInputError, PipelineError, SchemaValidationError
from app.processing.transformer import apply_transformations
from app.processing.validator import compare_schema, detect_truncation, normalize_headers
from app.recovery.workflow import FaultInjector, RetryPolicy, WorkflowEngine, WorkflowOutcome
from app.services import incident_service, storage
from app.services.dataset_service import read_dataset_bytes

logger = logging.getLogger("datapulse.pipeline")
STAGES = ["extract", "validate", "transform", "quality", "load"]


@dataclass
class RunContext:
    db: Session
    run: PipelineRun
    pipeline: Pipeline
    dataset: Dataset
    options: dict
    started: float
    raw: pd.DataFrame | None = None
    df: pd.DataFrame | None = None
    input_records: int | None = None
    truncation: dict | None = None
    header_changes: dict = field(default_factory=dict)
    applied_mapping: dict = field(default_factory=dict)
    schema_report: Any = None
    cleaning: Any = None
    output: pd.DataFrame | None = None
    transformations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    findings: list[rules.Finding] = field(default_factory=list)
    baseline: Baseline | None = None
    volume_note: dict = field(default_factory=dict)
    deviation: float = 0.0
    anomaly: dict = field(default_factory=dict)
    features: list[float] = field(default_factory=list)


# --------------------------------------------------------------------- stages
def _extract(ctx: RunContext) -> None:
    content = read_dataset_bytes(ctx.dataset)
    ctx.raw = load_dataframe(content, ctx.dataset.file_format)
    ctx.input_records = len(ctx.raw)
    ctx.truncation = detect_truncation(ctx.raw, get_settings().truncation_missing_fraction)


def _validate(ctx: RunContext) -> None:
    config = ctx.pipeline.config
    df, ctx.header_changes = normalize_headers(ctx.raw)
    mapping = ctx.options.get("column_mapping") or {}
    if mapping:
        df = df.rename(columns=mapping)
        ctx.applied_mapping = mapping
        ctx.transformations.append(f"Applied approved column mapping {mapping}")
    if ctx.header_changes:
        ctx.transformations.append(f"Normalised {len(ctx.header_changes)} column header(s)")
    ctx.schema_report = compare_schema(list(df.columns), config)
    if ctx.schema_report.missing_required:
        missing = ", ".join(ctx.schema_report.missing_required)
        raise SchemaValidationError(f"Required column(s) missing from input: {missing}",
                                    ctx.schema_report.to_dict())
    if ctx.truncation:
        raise IncompleteInputError(
            "Input appears truncated: the final record is incomplete "
            f"({ctx.truncation['last_row_missing_fraction'] * 100:.0f}% of its fields are empty)",
            {"truncation": ctx.truncation, "input_records": ctx.input_records})
    ctx.df = df


def _transform(ctx: RunContext) -> None:
    config = ctx.pipeline.config
    expected = [c for c in config["columns"] if c in ctx.df.columns]
    ctx.cleaning = clean_dataframe(ctx.df[expected], config)
    ctx.transformations.extend(ctx.cleaning.transformations)
    ctx.output, applied = apply_transformations(ctx.cleaning.clean, config)
    ctx.transformations.extend(applied)


def _quality(ctx: RunContext) -> None:
    s = get_settings()
    config = ctx.pipeline.config
    required = [c for c, spec in config["columns"].items() if spec.get("required", True)]
    ctx.metrics = compute_quality_metrics(input_records=ctx.input_records, cleaning=ctx.cleaning,
                                          schema_report=ctx.schema_report, required_columns=required,
                                          output_records=len(ctx.output))
    ctx.baseline = compute_baseline(ctx.db, ctx.pipeline.id, exclude_run_id=ctx.run.id,
                                    window=s.baseline_window, min_history=s.min_history_for_baseline)
    findings = rules.evaluate_quality_rules(ctx.metrics, s)
    findings += rules.evaluate_schema_drift(ctx.schema_report.to_dict())
    volume, ctx.deviation, ctx.volume_note = rules.evaluate_volume(ctx.input_records, ctx.baseline, s)
    findings += volume
    elapsed = time.perf_counter() - ctx.started
    findings += rules.evaluate_duration(elapsed, ctx.baseline, s)
    ctx.features = feature_vector(ctx.metrics, elapsed, ctx.deviation)
    ctx.anomaly = anomaly_detector.detect(ctx.pipeline.id, ctx.baseline.history_features, ctx.features,
                                          min_history=s.min_history_for_ml, models_dir=s.models_dir)
    if ctx.anomaly.get("is_anomaly"):
        if findings:
            for f in findings:
                f.evidence["isolation_forest_flagged"] = True
        else:
            findings.append(rules.Finding(
                "ML_ANOMALY", "anomaly", "medium", "Unusual combination of run metrics",
                {"decision_score": ctx.anomaly["decision_score"],
                 "top_deviating_features": ctx.anomaly["top_deviating_features"],
                 "history_size": ctx.anomaly["history_size"],
                 "note": "Isolation Forest flags unusual patterns; it does not identify causes."}))
    ctx.findings = findings


def _load(ctx: RunContext) -> None:
    run_id = ctx.run.id
    ctx.run.processed_filename = f"{run_id}_processed.csv.enc"
    storage.save_frame(ctx.output, ctx.run.processed_filename)
    if len(ctx.cleaning.quarantine):
        ctx.run.quarantine_filename = f"{run_id}_quarantine.csv.enc"
        storage.save_frame(ctx.cleaning.quarantine, ctx.run.quarantine_filename)


# ------------------------------------------------------------------ execution
def run_pipeline(db: Session, pipeline: Pipeline, dataset: Dataset, user: User | None, *,
                 trigger_type: str = "manual", parent_run_id: str | None = None,
                 options: dict | None = None, sleep=time.sleep) -> PipelineRun:
    s = get_settings()
    options = dict(options or {})
    run = PipelineRun(pipeline_id=pipeline.id, dataset_id=dataset.id, triggered_by=user.id if user else None,
                      trigger_type=trigger_type, parent_run_id=parent_run_id, status="running",
                      run_options=_public_options(options), is_synthetic=dataset.is_synthetic)
    db.add(run)
    db.commit()

    pre_baseline = compute_baseline(db, pipeline.id, exclude_run_id=run.id, window=s.repeated_failure_window,
                                    min_history=10**6)
    recent_failures = sum(1 for st in pre_baseline.recent_statuses[: s.repeated_failure_window] if st == "failed")
    retries_suspended = recent_failures >= s.repeated_failure_count
    policy = RetryPolicy(0 if retries_suspended else s.max_retries, s.retry_base_delay_seconds,
                         s.retry_backoff_factor)

    fault = None
    if options.get("fault_injection") and s.enable_fault_injection:
        fi = options["fault_injection"]
        fault = FaultInjector(fi.get("stage", "load"), int(fi.get("fail_times", 1)), fi.get("kind", "transient_db"))

    ctx = RunContext(db=db, run=run, pipeline=pipeline, dataset=dataset, options=options, started=time.perf_counter())
    engine = WorkflowEngine([("extract", _extract), ("validate", _validate), ("transform", _transform),
                             ("quality", _quality), ("load", _load)], policy, sleep=sleep, fault=fault)
    outcome = engine.run(ctx)

    _finalize(db, ctx, outcome, retries_suspended)
    return run


def _finalize(db: Session, ctx: RunContext, outcome: WorkflowOutcome, retries_suspended: bool) -> None:
    s = get_settings()
    run = ctx.run
    run.completed_at = datetime.now(timezone.utc)
    run.duration_seconds = round(time.perf_counter() - ctx.started, 4)
    run.stage_log = [st.to_dict() for st in outcome.stages]
    run.input_records = ctx.input_records
    retries = outcome.retries

    if outcome.status == "succeeded":
        run.output_records = len(ctx.output)
        run.quarantined_records = len(ctx.cleaning.quarantine)
        run.quality_score = ctx.metrics["quality_score"]
        run.metrics = {**ctx.metrics, "features": ctx.features}
        run.anomaly = ctx.anomaly
        has_issue = any(f.severity in ("medium", "high", "critical") for f in ctx.findings)
        run.status = "warning" if (has_issue or ctx.findings) else "succeeded"
        run.report = _build_report(ctx)
        run.summary = _summary(ctx, run.status)
    else:
        err = outcome.error
        run.status = "failed"
        run.failed_stage = outcome.failed_stage
        run.error_type = getattr(err, "error_type", type(err).__name__)
        run.error_message = outcome.stages[STAGES.index(outcome.failed_stage)].attempts[-1].error
        run.metrics = {"input_records": ctx.input_records} if ctx.input_records is not None else {}
        run.report = _build_report(ctx, error=err)
        run.summary = f"Failed at {outcome.failed_stage}: {run.error_message}"
    db.commit()

    incidents = []
    for finding in ctx.findings if outcome.status == "succeeded" else []:
        incidents.append(incident_service.create_from_finding(db, run, finding))

    if retries:
        incidents.append(incident_service.record_transient_retries(db, run, outcome, retries))

    if outcome.status == "failed":
        failure_incident = incident_service.create_from_failure(db, run, outcome, ctx, retries_suspended)
        if failure_incident is not None:
            incidents.append(failure_incident)
        baseline = compute_baseline(db, ctx.pipeline.id, exclude_run_id=run.id, window=s.repeated_failure_window,
                                    min_history=10**6)
        for finding in rules.evaluate_repeated_failures(True, baseline, s):
            incidents.append(incident_service.create_from_finding(db, run, finding))

    if outcome.status == "succeeded" and ctx.cleaning.duplicates_removed:
        dup_incident = next((i for i in incidents if i.rule_id == "DQ_DUPLICATES"), None)
        if dup_incident is not None:
            incident_service.record_auto_deduplication(db, run, dup_incident, ctx.cleaning.duplicates_removed)
    db.commit()
    logger.info("run %s finished status=%s in=%s out=%s incidents=%d", run.id, run.status,
                run.input_records, run.output_records, len(incidents))


def _public_options(options: dict) -> dict:
    allowed = {k: options[k] for k in ("column_mapping", "fault_injection") if options.get(k)}
    if "fault_injection" in allowed:
        allowed["fault_injection"] = {**allowed["fault_injection"], "simulated": True}
    return allowed


def _build_report(ctx: RunContext, error: BaseException | None = None) -> dict:
    report: dict = {
        "dataset": {"id": ctx.dataset.id, "filename": ctx.dataset.original_filename,
                    "format": ctx.dataset.file_format, "sha256": ctx.dataset.sha256,
                    "synthetic": ctx.dataset.is_synthetic},
        "header_normalisation": ctx.header_changes,
        "applied_column_mapping": ctx.applied_mapping,
        "schema": ctx.schema_report.to_dict() if ctx.schema_report else None,
        "transformations": ctx.transformations,
        "baseline": ctx.volume_note,
        "anomaly_detection": ctx.anomaly,
        "findings": [f.to_dict() for f in ctx.findings],
        "checks": _checks(ctx, error),
    }
    if ctx.cleaning is not None:
        reasons = Counter()
        for text in ctx.cleaning.quarantine.get("_rejection_reasons", pd.Series(dtype=str)):
            for part in str(text).split("; "):
                reasons[part] += 1
        report["quarantine_summary"] = dict(reasons.most_common())
        report["metrics"] = ctx.metrics
    if error is not None:
        report["error"] = {"type": getattr(error, "error_type", type(error).__name__),
                           "evidence": getattr(error, "evidence", {})}
    return report


def _checks(ctx: RunContext, error) -> list[dict]:
    """A flat pass/fail list of every validation check, for the quality report."""
    s = get_settings()
    checks = [{"check": "file_parsed", "passed": ctx.raw is not None}]
    if ctx.raw is not None:
        checks.append({"check": "input_complete", "passed": ctx.truncation is None})
    if ctx.schema_report is not None:
        checks.append({"check": "required_columns_present", "passed": not ctx.schema_report.missing_required,
                       "detail": ctx.schema_report.missing_required})
        checks.append({"check": "no_unexpected_columns", "passed": not ctx.schema_report.unexpected_columns,
                       "detail": ctx.schema_report.unexpected_columns})
    if ctx.metrics:
        m = ctx.metrics
        checks += [
            {"check": "duplicate_rate_within_threshold", "passed": m["duplicate_pct"] <= s.duplicate_rate_threshold * 100,
             "value": m["duplicate_pct"]},
            {"check": "missing_rate_within_threshold", "passed": m["missing_pct"] <= s.missing_rate_threshold * 100,
             "value": m["missing_pct"]},
            {"check": "invalid_rate_within_threshold", "passed": m["invalid_pct"] <= s.invalid_rate_threshold * 100,
             "value": m["invalid_pct"]},
            {"check": "record_volume_within_baseline",
             "passed": not any(f.incident_type == "volume" for f in ctx.findings),
             "value": ctx.volume_note.get("deviation_pct"), "status": ctx.volume_note.get("status")},
            {"check": "isolation_forest_normal", "passed": not ctx.anomaly.get("is_anomaly", False),
             "status": ctx.anomaly.get("status")},
        ]
    return checks


def _summary(ctx: RunContext, status: str) -> str:
    m = ctx.metrics
    parts = [f"{m['input_records']:,} records in, {m['output_records']:,} out, "
             f"{m['quarantined_records']:,} quarantined; quality score {m['quality_score']:.1f}."]
    if ctx.findings:
        parts.append("Findings: " + "; ".join(f.title for f in ctx.findings) + ".")
    return " ".join(parts)


def validate_output(run: PipelineRun, config: dict) -> tuple[bool, list[str]]:
    """Independently re-read the stored output and verify it meets the pipeline contract."""
    problems: list[str] = []
    if run.status == "failed" or not run.processed_filename:
        return False, ["run did not produce an output file"]
    try:
        df = storage.load_frame(run.processed_filename)
    except Exception as exc:  # noqa: BLE001
        return False, [f"output could not be read: {type(exc).__name__}"]
    if len(df) != run.output_records:
        problems.append(f"row count {len(df)} does not match recorded {run.output_records}")
    required = [c for c, spec in config["columns"].items() if spec.get("required", True)]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        problems.append(f"output missing columns {missing_cols}")
    else:
        nulls = int(df[required].isna().sum().sum())
        if nulls:
            problems.append(f"{nulls} null values in required output columns")
    key = [k for k in config.get("business_key", []) if k in df.columns]
    if key and df.duplicated(subset=key).any():
        problems.append("business key is not unique in output")
    return not problems, problems


def get_pipeline(db: Session, pipeline_id: int) -> Pipeline | None:
    return db.get(Pipeline, pipeline_id)


def list_runs(db: Session, pipeline_id: int | None = None, status: str | None = None,
              limit: int = 50, offset: int = 0) -> list[PipelineRun]:
    q = select(PipelineRun).order_by(PipelineRun.started_at.desc())
    if pipeline_id:
        q = q.where(PipelineRun.pipeline_id == pipeline_id)
    if status:
        q = q.where(PipelineRun.status == status)
    return list(db.scalars(q.offset(offset).limit(limit)))
