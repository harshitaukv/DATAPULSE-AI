"""Incident creation and automatic recovery records."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Incident, PipelineRun, RecoveryLog
from app.monitoring.rules import Finding
from app.processing.errors import IncompleteInputError, SchemaValidationError, TransientError
from app.recovery.policies import policy_for


def _new_incident(db: Session, run: PipelineRun, *, incident_type: str, rule_id: str, severity: str,
                  title: str, evidence: dict) -> Incident:
    policy = policy_for(rule_id)
    incident = Incident(run_id=run.id, pipeline_id=run.pipeline_id, incident_type=incident_type, rule_id=rule_id,
                        severity=severity, title=title, evidence=evidence, probable_cause=policy.probable_cause,
                        recommended_action=policy.recommended_action, recovery_policy=policy.name)
    db.add(incident)
    db.flush()
    return incident


def create_from_finding(db: Session, run: PipelineRun, finding: Finding) -> Incident:
    return _new_incident(db, run, incident_type=finding.incident_type, rule_id=finding.rule_id,
                         severity=finding.severity, title=finding.title, evidence=finding.evidence)


def create_from_failure(db: Session, run: PipelineRun, outcome, ctx, retries_suspended: bool) -> Incident | None:
    err = outcome.error
    evidence = {"failed_stage": outcome.failed_stage, "error_type": run.error_type,
                "error_message": run.error_message, "input_records": run.input_records,
                "dataset_filename": ctx.dataset.original_filename}
    evidence.update({k: v for k, v in getattr(err, "evidence", {}).items()})
    if ctx.input_records is not None and ctx.baseline is None:
        # The run failed before the quality stage; still record volume context when history allows.
        from app.config import get_settings
        from app.monitoring.baseline import compute_baseline
        from app.monitoring.rules import evaluate_volume
        s = get_settings()
        b = compute_baseline(db, run.pipeline_id, exclude_run_id=run.id, window=s.baseline_window,
                             min_history=s.min_history_for_baseline)
        vol, _, note = evaluate_volume(ctx.input_records, b, s)
        evidence["volume_check"] = vol[0].evidence if vol else note
    if retries_suspended:
        evidence["automatic_retries"] = "suspended (repeated failures on this pipeline)"

    if isinstance(err, SchemaValidationError):
        return _new_incident(db, run, incident_type="schema", rule_id="SCHEMA_MISSING_COLUMNS",
                             severity="critical",
                             title=f"Required column missing: {', '.join(err.evidence.get('missing_required', []))}",
                             evidence=evidence)
    if isinstance(err, IncompleteInputError):
        return _new_incident(db, run, incident_type="incomplete_input", rule_id="INPUT_TRUNCATED",
                             severity="high", title="Input file appears incomplete (truncated record)",
                             evidence=evidence)
    if isinstance(err, TransientError) or getattr(err, "retryable", False):
        return None  # covered by record_transient_retries, which already opened the incident
    return _new_incident(db, run, incident_type="runtime", rule_id="RUNTIME_STAGE_FAILURE", severity="high",
                         title=f"Stage '{outcome.failed_stage}' failed: {run.error_type}", evidence=evidence)


def record_transient_retries(db: Session, run: PipelineRun, outcome, retries) -> Incident:
    recovered = outcome.status == "succeeded"
    stage = retries[0][0]
    attempts = [a for st in outcome.stages if st.name == stage for a in st.attempts]
    evidence = {"stage": stage, "attempts": [a.__dict__ for a in attempts],
                "errors": sorted({a.error for a in attempts if a.error}),
                "simulated": bool(run.run_options.get("fault_injection")),
                "recovered_automatically": recovered}
    incident = _new_incident(db, run, incident_type="transient_failure", rule_id="RUNTIME_TRANSIENT",
                             severity="medium" if recovered else "high",
                             title=f"Transient failure in '{stage}' stage"
                                   + (" (recovered by retry)" if recovered else " (retries exhausted)"),
                             evidence=evidence)
    for n, (previous, current) in enumerate(zip(attempts, attempts[1:]), start=1):
        db.add(RecoveryLog(incident_id=incident.id, recovery_run_id=run.id, action="retry_stage", mode="automatic",
                           attempt_number=n, result="success" if current.status == "succeeded" else "failure",
                           details={"stage": stage, "backoff_seconds": previous.retry_delay_seconds,
                                    "triggering_error": previous.error,
                                    "outcome": "stage succeeded on retry" if current.status == "succeeded"
                                    else "retry failed"},
                           error_message=current.error, approval_status="not_required"))
    if not recovered:
        db.add(RecoveryLog(incident_id=incident.id, recovery_run_id=run.id, action="escalate", mode="automatic",
                           attempt_number=len(attempts), result="requires_manual",
                           details={"reason": "retry limit reached" if len(attempts) > 1
                                    else "automatic retries suspended for this pipeline",
                                    "attempts_made": len(attempts)},
                           approval_status="not_required"))
    if recovered:
        from app.services.pipeline_service import validate_output
        ok, problems = validate_output(run, run.pipeline.config)
        if ok:
            incident.status = "resolved"
            incident.resolved_at = datetime.now(timezone.utc)
            incident.resolution_notes = (f"Recovered automatically after {len(retries)} retr"
                                         f"{'y' if len(retries) == 1 else 'ies'}; output validated "
                                         f"({run.output_records:,} rows, required columns complete, key unique).")
        else:
            incident.resolution_notes = "Stage recovered but output validation failed: " + "; ".join(problems)
    else:
        incident.resolution_notes = "Retry limit reached; manual investigation required."
    return incident


def record_auto_deduplication(db: Session, run: PipelineRun, incident: Incident, removed: int) -> None:
    from app.services.pipeline_service import validate_output
    ok, problems = validate_output(run, run.pipeline.config)
    db.add(RecoveryLog(incident_id=incident.id, recovery_run_id=run.id, action="apply_deduplication",
                       mode="automatic", attempt_number=1, result="success" if ok else "failure",
                       details={"policy": "keep_first", "business_key": run.pipeline.config.get("business_key"),
                                "rows_quarantined": removed, "output_validation": "passed" if ok else problems},
                       approval_status="not_required"))
    incident.resolution_notes = (f"{removed} duplicate rows quarantined under keep_first; output verified unique. "
                                 "Source still delivers duplicates - fix the extract upstream.")


def next_attempt_number(db: Session, incident_id: str) -> int:
    count = db.scalar(select(func.count()).select_from(RecoveryLog).where(RecoveryLog.incident_id == incident_id))
    return int(count or 0) + 1
