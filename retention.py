"""Data retention: remove uploaded files and outputs older than RETENTION_DAYS.

Metadata (runs, incidents, audit) is kept for traceability; only the stored
record-level files are deleted, and datasets are marked deleted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Dataset, PipelineRun
from app.services.storage import processed_path, upload_path


def apply_retention(db: Session, days: int, dry_run: bool = True) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    datasets = list(db.scalars(select(Dataset).where(Dataset.uploaded_at < cutoff, Dataset.deleted_at.is_(None))))
    runs = list(db.scalars(select(PipelineRun).where(PipelineRun.started_at < cutoff)))
    files = sum(1 for r in runs for f in (r.processed_filename, r.quarantine_filename) if f)
    if not dry_run:
        for ds in datasets:
            upload_path(ds.stored_filename).unlink(missing_ok=True)
            ds.deleted_at = datetime.now(timezone.utc)
        for r in runs:
            for f in (r.processed_filename, r.quarantine_filename):
                if f:
                    processed_path(f).unlink(missing_ok=True)
            r.processed_filename = r.quarantine_filename = None
        db.commit()
    return {"retention_days": days, "cutoff": cutoff.isoformat(), "datasets_affected": len(datasets),
            "output_files_affected": files, "applied": not dry_run}
