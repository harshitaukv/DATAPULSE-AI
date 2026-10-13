"""Recovery policy catalogue.

The LLM may *recommend* actions in prose, but only the actions listed here can
be executed, and only through the recovery service, which enforces
authorisation, approval, retry limits and output validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ACTIONS = {
    "retry_run": "Re-run the pipeline on the same stored input (transient failures only).",
    "rerun_with_dataset": "Re-run the pipeline on a corrected dataset that has already been uploaded.",
    "apply_column_mapping": "Re-run with an explicit column rename mapping (admin approval required).",
    "escalate": "Stop automatic handling and route the incident for manual investigation.",
}
APPROVAL_REQUIRED = {"apply_column_mapping"}


@dataclass(frozen=True)
class RecoveryPolicy:
    name: str
    automatic: str
    allowed_actions: tuple[str, ...]
    probable_cause: str
    recommended_action: str
    retry_eligible: bool = False
    notes: list[str] = field(default_factory=list)


POLICIES: dict[str, RecoveryPolicy] = {
    "RUNTIME_TRANSIENT": RecoveryPolicy(
        "retry_with_backoff", "Retried automatically with exponential backoff up to the retry limit.",
        ("retry_run", "escalate"),
        "A temporary infrastructure condition (connection reset, lock or I/O timeout) interrupted a stage.",
        "Retry the run. If retries keep failing, check database/storage availability before retrying again.",
        retry_eligible=True),
    "INPUT_TRUNCATED": RecoveryPolicy(
        "request_corrected_file", "Processing stopped; the original input is preserved.",
        ("rerun_with_dataset", "escalate"),
        "The source file appears to have been cut off during extraction or transfer.",
        "Ask the source owner to re-deliver the complete file, upload it, then re-run with the new dataset."),
    "SCHEMA_MISSING_COLUMNS": RecoveryPolicy(
        "request_schema_correction", "The affected transformation was stopped; no output was written.",
        ("apply_column_mapping", "rerun_with_dataset", "escalate"),
        "The source schema changed: a required column is absent, possibly renamed upstream.",
        "Confirm the change with the source owner. If a column was only renamed, apply a column mapping "
        "(admin approval); otherwise request a corrected file."),
    "SCHEMA_DRIFT": RecoveryPolicy(
        "review_schema_change", "Unexpected columns were ignored; expected columns were processed.",
        ("rerun_with_dataset", "escalate"),
        "The source added columns that the pipeline contract does not declare.",
        "Decide whether the new columns should be added to the pipeline contract or removed at source."),
    "DQ_DUPLICATES": RecoveryPolicy(
        "deduplicate_keep_first", "Duplicates with a valid business key were quarantined (keep_first).",
        ("rerun_with_dataset", "escalate"),
        "The same transactions were delivered more than once (upstream replay or overlapping extracts).",
        "Review the quarantined duplicates and fix the overlapping extract window at source."),
    "DQ_MISSING_VALUES": RecoveryPolicy(
        "quarantine_and_review", "Rows missing required values were quarantined with reasons.",
        ("rerun_with_dataset", "escalate"),
        "Required fields were not populated by the source system for part of the batch.",
        "Inspect the quarantine report by column and ask the source owner to backfill the missing fields."),
    "DQ_INVALID_VALUES": RecoveryPolicy(
        "quarantine_and_review", "Invalid rows were quarantined with the rule they violated.",
        ("rerun_with_dataset", "escalate"),
        "The source produced values that violate type or business constraints.",
        "Review the violated constraints in the quarantine report and correct the source records."),
    "VOLUME_DROP": RecoveryPolicy(
        "validate_source_volume", "Records were processed; the volume deviation was flagged for review.",
        ("rerun_with_dataset", "escalate"),
        "Possible incomplete extraction or a partial delivery. A genuine business change is also possible.",
        "Confirm the expected volume with the source owner. If data is missing, re-deliver and re-run."),
    "VOLUME_SPIKE": RecoveryPolicy(
        "validate_source_volume", "Records were processed; the volume deviation was flagged for review.",
        ("rerun_with_dataset", "escalate"),
        "Possible duplicated extraction window or a genuine business spike.",
        "Check for overlapping extracts and confirm with the business owner."),
    "PERF_SLOW_RUN": RecoveryPolicy(
        "monitor", "No action taken; duration is tracked.", ("escalate",),
        "Processing took much longer than usual (resource contention or larger input).",
        "Monitor the next runs. Escalate if the slowdown persists."),
    "ML_ANOMALY": RecoveryPolicy(
        "investigate_anomaly", "Flagged for investigation; data was processed normally.",
        ("rerun_with_dataset", "escalate"),
        "The combination of run metrics is unusual compared with this pipeline's history.",
        "Compare the deviating features with previous runs to decide whether this is a real problem."),
    "RUNTIME_STAGE_FAILURE": RecoveryPolicy(
        "preserve_logs_investigate", "Stage logs were preserved; the error is not eligible for automatic retry.",
        ("escalate", "rerun_with_dataset"),
        "A processing stage raised a non-transient error.",
        "Inspect the stage log and error, fix the cause, then re-run."),
    "REPEATED_FAILURE": RecoveryPolicy(
        "stop_and_manual_review", "Automatic retries are suspended for this pipeline until review.",
        ("escalate", "rerun_with_dataset"),
        "The pipeline keeps failing, so the cause is persistent rather than transient.",
        "Investigate the failing stage across recent runs before running again."),
}


def policy_for(rule_id: str) -> RecoveryPolicy:
    return POLICIES.get(rule_id, POLICIES["RUNTIME_STAGE_FAILURE"])


def describe_policies() -> list[dict]:
    return [{"rule_id": rid, "policy": p.name, "automatic_behaviour": p.automatic,
             "allowed_actions": list(p.allowed_actions), "retry_eligible": p.retry_eligible}
            for rid, p in POLICIES.items()]
