"""Deterministic, configurable detection rules.

Each rule produces a Finding with the measured evidence that triggered it.
Thresholds come from settings so they can be tuned per deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.monitoring.baseline import Baseline


@dataclass
class Finding:
    rule_id: str
    incident_type: str
    severity: str
    title: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "incident_type": self.incident_type, "severity": self.severity,
                "title": self.title, "evidence": self.evidence}


def evaluate_quality_rules(metrics: dict, s: Settings) -> list[Finding]:
    findings: list[Finding] = []
    dup = metrics["duplicate_pct"] / 100
    if dup > s.duplicate_rate_threshold:
        findings.append(Finding("DQ_DUPLICATES", "data_quality", "high" if dup > 0.10 else "medium",
                                f"Duplicate rate {metrics['duplicate_pct']:.2f}% exceeds threshold",
                                {"duplicate_records": metrics["duplicate_records"],
                                 "duplicate_pct": metrics["duplicate_pct"],
                                 "duplicates_quarantined": metrics["duplicates_removed"],
                                 "threshold_pct": s.duplicate_rate_threshold * 100}))
    # Row-level: share of rows unusable because a required value is missing (matches the completeness score).
    miss = metrics["missing_rows_pct"] / 100
    missing_cols = {k: v for k, v in metrics["missing_by_column"].items() if v}
    if miss > s.missing_rate_threshold:
        findings.append(Finding("DQ_MISSING_VALUES", "data_quality", "high" if miss > 0.20 else "medium",
                                f"{metrics['missing_rows_pct']:.2f}% of rows are missing required values",
                                {"rows_with_missing_required": metrics["rows_with_missing_required"],
                                 "missing_rows_pct": metrics["missing_rows_pct"],
                                 "missing_cells_pct": metrics["missing_pct"],
                                 "missing_by_column": missing_cols,
                                 "threshold_pct": s.missing_rate_threshold * 100}))
    inv = metrics["invalid_pct"] / 100
    if inv > s.invalid_rate_threshold:
        findings.append(Finding("DQ_INVALID_VALUES", "data_quality", "high" if inv > 0.10 else "medium",
                                f"Invalid-record rate {metrics['invalid_pct']:.2f}% exceeds threshold",
                                {"invalid_records": metrics["invalid_records"], "invalid_pct": metrics["invalid_pct"],
                                 "type_errors_by_column": {k: v for k, v in metrics["type_errors_by_column"].items() if v},
                                 "constraint_violations": {k: v for k, v in metrics["constraint_violations"].items() if v},
                                 "threshold_pct": s.invalid_rate_threshold * 100}))
    return findings


def evaluate_schema_drift(schema: dict) -> list[Finding]:
    if schema.get("unexpected_columns") and not schema.get("missing_required"):
        return [Finding("SCHEMA_DRIFT", "schema", "medium", "Unexpected columns in the source data",
                        {"unexpected_columns": schema["unexpected_columns"],
                         "expected_columns": schema["expected_columns"]})]
    return []


def evaluate_volume(input_records: int, baseline: Baseline, s: Settings) -> tuple[list[Finding], float, dict]:
    """Return findings, the relative deviation (0 when no baseline), and a status note."""
    if not baseline.sufficient:
        note = {"status": "insufficient_history", "completed_runs": baseline.sample_size,
                "required": s.min_history_for_baseline}
        return [], 0.0, note
    deviation = (input_records - baseline.median_records) / baseline.median_records
    note = {"status": "evaluated", "baseline_median_records": baseline.median_records,
            "baseline_runs": baseline.sample_size, "deviation_pct": round(100 * deviation, 2)}
    evidence = {"input_records": input_records, "baseline_median_records": baseline.median_records,
                "baseline_runs": baseline.sample_size, "deviation_pct": round(100 * deviation, 2)}
    if deviation <= -s.volume_drop_threshold:
        sev = "critical" if deviation <= -0.9 else "high"
        return [Finding("VOLUME_DROP", "volume", sev,
                        f"Record count dropped {abs(deviation) * 100:.0f}% below baseline", evidence)], deviation, note
    if deviation >= s.volume_spike_threshold:
        return [Finding("VOLUME_SPIKE", "volume", "medium",
                        f"Record count is {deviation * 100:.0f}% above baseline", evidence)], deviation, note
    return [], deviation, note


def evaluate_duration(duration: float, baseline: Baseline, s: Settings) -> list[Finding]:
    if not baseline.sufficient or not baseline.median_duration:
        return []
    limit = max(baseline.median_duration * s.duration_factor_threshold, s.duration_min_seconds)
    if duration > limit:
        return [Finding("PERF_SLOW_RUN", "performance", "low",
                        f"Processing took {duration:.1f}s (normal ≈ {baseline.median_duration:.1f}s)",
                        {"duration_seconds": round(duration, 3), "baseline_median_seconds": baseline.median_duration,
                         "limit_seconds": round(limit, 3)})]
    return []


def evaluate_repeated_failures(current_failed: bool, baseline: Baseline, s: Settings) -> list[Finding]:
    statuses = baseline.recent_statuses[: s.repeated_failure_window - 1]
    failures = sum(1 for st in statuses if st == "failed") + (1 if current_failed else 0)
    if current_failed and failures >= s.repeated_failure_count:
        return [Finding("REPEATED_FAILURE", "repeated_failure", "critical",
                        f"{failures} of the last {len(statuses) + 1} runs failed",
                        {"failed_runs": failures, "window": len(statuses) + 1,
                         "threshold": s.repeated_failure_count,
                         "automatic_retries": "disabled until manual review"})]
    return []
