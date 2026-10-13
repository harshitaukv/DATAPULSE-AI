"""Controlled recovery: executes only catalogued actions, never free-form commands.

Workflow: classify incident -> check eligibility & authorisation -> (approval) ->
execute -> validate output independently -> record outcome -> update incident.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import Dataset, Incident, PipelineRun, RecoveryLog, User
from app.processing.validator import normalize_column_name
from app.recovery.policies import APPROVAL_REQUIRED, policy_for
from app.security.authorization import has_permission
from app.services import pipeline_service
from app.services.incident_service import next_attempt_number


class RecoveryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def eligible_actions(db: Session, incident: Incident) -> list[str]:
    if incident.status in ("resolved", "closed"):
        return []
    actions = list(policy_for(incident.rule_id).allowed_actions)
    if "retry_run" in actions and _manual_retries(db, incident.id) >= get_settings().max_retries:
        actions.remove("retry_run")
    if "retry_run" in actions and _pipeline_retries_suspended(db, incident.pipeline_id):
        actions.remove("retry_run")
    return actions


def _manual_retries(db: Session, incident_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(RecoveryLog).where(
        RecoveryLog.incident_id == incident_id, RecoveryLog.action == "retry_run",
        RecoveryLog.mode == "manual")) or 0)


def _pipeline_retries_suspended(db: Session, pipeline_id: int) -> bool:
    return db.scalar(select(func.count()).select_from(Incident).where(
        Incident.pipeline_id == pipeline_id, Incident.rule_id == "REPEATED_FAILURE",
        Incident.status.in_(("open", "under_review")))) > 0


def request_recovery(db: Session, incident: Incident, user: User, action: str, *, dataset_id: str | None = None,
                     column_mapping: dict | None = None, notes: str = "",
                     idempotency_key: str | None = None) -> RecoveryLog:
    if idempotency_key:
        existing = db.scalar(select(RecoveryLog).where(RecoveryLog.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.incident_id != incident.id:
                raise RecoveryError("Idempotency key already used for a different incident.", 409)
            return existing

    if incident.status in ("resolved", "closed"):
        raise RecoveryError(f"Incident is already {incident.status}; no recovery is needed.", 409)
    policy = policy_for(incident.rule_id)
    if action not in policy.allowed_actions:
        raise RecoveryError(f"Action '{action}' is not permitted by the '{policy.name}' policy. "
                            f"Allowed: {', '.join(policy.allowed_actions)}.")
    if action not in eligible_actions(db, incident):
        raise RecoveryError("Retry limit reached or automatic retries are suspended for this pipeline; "
                            "escalate or re-run with a corrected dataset instead.", 409)

    params: dict = {"notes": notes[:1000]} if notes else {}
    if action == "rerun_with_dataset":
        ds = db.get(Dataset, dataset_id) if dataset_id else None
        if ds is None or ds.deleted_at is not None:
            raise RecoveryError("A valid, uploaded dataset_id is required for rerun_with_dataset.")
        params["dataset_id"] = ds.id
    if action == "apply_column_mapping":
        params["column_mapping"] = _validate_mapping(db, incident, column_mapping or {})

    log = RecoveryLog(incident_id=incident.id, action=action, mode="manual",
                      attempt_number=next_attempt_number(db, incident.id), result="pending",
                      details=params, idempotency_key=idempotency_key, requested_by=user.id,
                      approval_status="pending" if action in APPROVAL_REQUIRED else "not_required")
    db.add(log)
    db.flush()

    if action in APPROVAL_REQUIRED:
        if has_permission(user, "approve_recovery"):
            log.approval_status = "approved"
            log.approved_by = user.id
        else:
            db.commit()
            return log  # waits for an administrator
    return _execute(db, incident, log, user)


def decide_approval(db: Session, log: RecoveryLog, admin: User, approve: bool, reason: str = "") -> RecoveryLog:
    if log.approval_status != "pending":
        raise RecoveryError(f"Recovery request is not pending approval (status: {log.approval_status}).", 409)
    incident = db.get(Incident, log.incident_id)
    if not approve:
        log.approval_status, log.result, log.approved_by = "rejected", "skipped", admin.id
        log.details = {**log.details, "rejection_reason": reason[:500]}
        db.commit()
        return log
    if incident.status in ("resolved", "closed"):
        raise RecoveryError("Incident was resolved while the request was pending.", 409)
    log.approval_status, log.approved_by = "approved", admin.id
    return _execute(db, incident, log, admin)


def _validate_mapping(db: Session, incident: Incident, mapping: dict) -> dict:
    if not mapping or not isinstance(mapping, dict):
        raise RecoveryError("column_mapping must be a non-empty object of {source_column: expected_column}.")
    run = db.get(PipelineRun, incident.run_id)
    ds = db.get(Dataset, run.dataset_id) if run and run.dataset_id else None
    if ds is None:
        raise RecoveryError("The original dataset for this incident is no longer available.", 409)
    expected = set(run.pipeline.config["columns"])
    available = {normalize_column_name(c) for c in ds.columns}
    clean: dict[str, str] = {}
    for src, dst in mapping.items():
        src_n, dst_n = normalize_column_name(src), normalize_column_name(dst)
        if src_n not in available:
            raise RecoveryError(f"Source column '{src}' does not exist in the dataset.")
        if dst_n not in expected:
            raise RecoveryError(f"Target column '{dst}' is not part of the pipeline contract.")
        if dst_n in available:
            raise RecoveryError(f"Target column '{dst}' already exists in the dataset.")
        clean[src_n] = dst_n
    if len(set(clean.values())) != len(clean):
        raise RecoveryError("Two source columns cannot map to the same target column.")
    return clean


def _execute(db: Session, incident: Incident, log: RecoveryLog, user: User) -> RecoveryLog:
    action = log.action
    original_run = db.get(PipelineRun, incident.run_id)

    if action == "escalate":
        incident.status = "under_review"
        log.result = "requires_manual"
        log.details = {**log.details, "outcome": "Routed for manual investigation"}
        db.commit()
        return log

    if action == "retry_run":
        dataset = db.get(Dataset, original_run.dataset_id)
        options = {}
    elif action == "rerun_with_dataset":
        dataset = db.get(Dataset, log.details["dataset_id"])
        options = {}
    elif action == "apply_column_mapping":
        dataset = db.get(Dataset, original_run.dataset_id)
        options = {"column_mapping": log.details["column_mapping"]}
    else:  # pragma: no cover - guarded by policy check
        raise RecoveryError(f"Unsupported action {action}")
    if dataset is None or dataset.deleted_at is not None:
        log.result, log.error_message = "failure", "Input dataset is no longer available."
        db.commit()
        return log

    db.commit()  # persist the pending log before running
    new_run = pipeline_service.run_pipeline(db, original_run.pipeline, dataset, user, trigger_type="recovery",
                                            parent_run_id=original_run.id, options=options)
    log.recovery_run_id = new_run.id
    ok, problems = pipeline_service.validate_output(new_run, original_run.pipeline.config)
    recurred = [i.rule_id for i in new_run.incidents if i.rule_id == incident.rule_id]
    if ok and not recurred:
        log.result = "success"
        incident.status = "resolved"
        incident.resolved_at = datetime.now(timezone.utc)
        incident.resolution_notes = (f"Resolved by {action} (run {new_run.id[:8]}): output validated with "
                                     f"{new_run.output_records:,} rows.")
    else:
        log.result = "failure"
        reasons = problems + ([f"rule {incident.rule_id} triggered again"] if recurred else [])
        log.error_message = "; ".join(reasons) or f"recovery run finished with status {new_run.status}"
    log.details = {**log.details, "recovery_run_status": new_run.status,
                   "output_validation": "passed" if ok else problems,
                   "new_incidents": [i.rule_id for i in new_run.incidents]}
    db.commit()
    return log
