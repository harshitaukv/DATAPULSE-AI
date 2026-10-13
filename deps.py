"""Shared API helpers: serialisers and lookups."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Dataset, Incident, PipelineRun, RecoveryLog, User
from app.schemas import DatasetOut, IncidentOut, RecoveryLogOut, RunDetail, RunSummary


def get_or_404(db: Session, model, key, label: str):
    obj = db.get(model, key)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


def dataset_out(ds: Dataset) -> DatasetOut:
    out = DatasetOut.model_validate(ds)
    out.uploaded_by_username = ds.uploader.username if ds.uploader else None
    return out


def run_summary(db: Session, run: PipelineRun, detail: bool = False) -> RunSummary:
    model = RunDetail if detail else RunSummary
    out = model.model_validate(run)
    out.pipeline_name = run.pipeline.name if run.pipeline else None
    out.dataset_filename = run.dataset.original_filename if run.dataset else None
    out.incident_count = db.scalar(select(func.count()).select_from(Incident).where(Incident.run_id == run.id)) or 0
    if detail:
        out.has_processed_file = bool(run.processed_filename)
        out.has_quarantine_file = bool(run.quarantine_filename)
    return out


def incident_out(db: Session, inc: Incident, with_actions: bool = True) -> IncidentOut:
    from app.services.recovery_service import eligible_actions
    out = IncidentOut.model_validate(inc)
    out.run_status = inc.run.status if inc.run else None
    out.dataset_filename = inc.run.dataset.original_filename if inc.run and inc.run.dataset else None
    if with_actions:
        out.eligible_actions = eligible_actions(db, inc)
    return out


def log_out(db: Session, log: RecoveryLog) -> RecoveryLogOut:
    out = RecoveryLogOut.model_validate(log)
    names = {}
    for uid in {log.requested_by, log.approved_by} - {None}:
        u = db.get(User, uid)
        names[uid] = u.username if u else None
    out.requested_by_username = names.get(log.requested_by) if log.requested_by else ("system" if log.mode == "automatic" else None)
    out.approved_by_username = names.get(log.approved_by)
    out.incident_title = log.incident.title if log.incident else None
    return out
