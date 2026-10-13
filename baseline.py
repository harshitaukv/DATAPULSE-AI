"""Historical baselines computed from persisted pipeline runs."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PipelineRun


@dataclass
class Baseline:
    sample_size: int
    median_records: float | None
    median_duration: float | None
    median_missing_pct: float | None
    median_duplicate_pct: float | None
    recent_statuses: list[str]
    history_features: list[list[float]]

    @property
    def sufficient(self) -> bool:
        return self.median_records is not None


def compute_baseline(db: Session, pipeline_id: int, *, exclude_run_id: str | None, window: int,
                     min_history: int) -> Baseline:
    q = (select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
         .order_by(PipelineRun.started_at.desc()).limit(window + 1))
    runs = [r for r in db.scalars(q) if r.id != exclude_run_id][:window]
    completed = [r for r in runs if r.status in ("succeeded", "warning") and r.input_records]
    statuses = [r.status for r in runs]
    features = [r.metrics.get("features") for r in completed if r.metrics.get("features")]
    if len(completed) < min_history:
        return Baseline(len(completed), None, None, None, None, statuses, features)
    return Baseline(
        sample_size=len(completed),
        median_records=statistics.median(r.input_records for r in completed),
        median_duration=statistics.median(r.duration_seconds or 0 for r in completed),
        median_missing_pct=statistics.median(r.metrics.get("missing_pct", 0) for r in completed),
        median_duplicate_pct=statistics.median(r.metrics.get("duplicate_pct", 0) for r in completed),
        recent_statuses=statuses,
        history_features=features,
    )
