"""Aggregated metrics for the dashboard. Every value is computed from stored records."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Incident, PipelineRun, RecoveryLog, User
from app.security.authorization import require

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview")
def overview(include_seed: bool = True, db: Session = Depends(get_db), _: User = Depends(require("read"))):
    run_filter = [] if include_seed else [PipelineRun.trigger_type != "seed"]
    by_status = dict(db.execute(select(PipelineRun.status, func.count()).where(*run_filter)
                                .group_by(PipelineRun.status)).all())
    total = sum(by_status.values())
    avg_q = db.scalar(select(func.avg(PipelineRun.quality_score)).where(PipelineRun.quality_score.is_not(None),
                                                                         *run_filter))
    inc_status = dict(db.execute(select(Incident.status, func.count()).group_by(Incident.status)).all())
    open_sev = dict(db.execute(select(Incident.severity, func.count())
                               .where(Incident.status.in_(("open", "under_review"))).group_by(Incident.severity)).all())
    rec = dict(db.execute(select(RecoveryLog.result, func.count()).group_by(RecoveryLog.result)).all())
    attempted = rec.get("success", 0) + rec.get("failure", 0)
    pending_approvals = db.scalar(select(func.count()).select_from(RecoveryLog)
                                  .where(RecoveryLog.approval_status == "pending")) or 0
    records = db.scalar(select(func.sum(PipelineRun.input_records)).where(*run_filter)) or 0
    return {
        "total_runs": total,
        "succeeded": by_status.get("succeeded", 0),
        "warnings": by_status.get("warning", 0),
        "failed": by_status.get("failed", 0),
        "running": by_status.get("running", 0),
        "success_rate": round(100 * (by_status.get("succeeded", 0) + by_status.get("warning", 0)) / total, 2) if total else None,
        "average_quality_score": round(float(avg_q), 2) if avg_q is not None else None,
        "records_processed": int(records),
        "open_incidents": inc_status.get("open", 0) + inc_status.get("under_review", 0),
        "incidents_by_status": inc_status,
        "open_incidents_by_severity": open_sev,
        "recovery_attempts": attempted,
        "recovery_successes": rec.get("success", 0),
        "recovery_success_rate": round(100 * rec.get("success", 0) / attempted, 2) if attempted else None,
        "pending_approvals": pending_approvals,
    }


@router.get("/trends")
def trends(days: int = Query(60, ge=1, le=365), db: Session = Depends(get_db), _: User = Depends(require("read"))):
    runs = db.execute(select(PipelineRun.started_at, PipelineRun.status, PipelineRun.quality_score,
                             PipelineRun.input_records, PipelineRun.duration_seconds, PipelineRun.id,
                             PipelineRun.trigger_type, PipelineRun.metrics)
                      .order_by(PipelineRun.started_at.desc()).limit(days * 50)).all()
    per_day: dict[str, dict] = defaultdict(lambda: {"succeeded": 0, "warning": 0, "failed": 0, "running": 0})
    series = []
    for started, status, q, n, dur, rid, trig, metrics in reversed(runs):
        per_day[started.date().isoformat()][status] = per_day[started.date().isoformat()].get(status, 0) + 1
        series.append({"run_id": rid, "started_at": started.isoformat(), "status": status, "quality_score": q,
                       "input_records": n, "duration_seconds": dur, "trigger_type": trig,
                       "missing_pct": (metrics or {}).get("missing_pct"),
                       "duplicate_pct": (metrics or {}).get("duplicate_pct"),
                       "invalid_pct": (metrics or {}).get("invalid_pct")})
    sev = dict(db.execute(select(Incident.severity, func.count()).group_by(Incident.severity)).all())
    types = dict(db.execute(select(Incident.incident_type, func.count()).group_by(Incident.incident_type)).all())
    return {"runs_per_day": [{"date": d, **v} for d, v in sorted(per_day.items())], "run_series": series,
            "incidents_by_severity": sev, "incidents_by_type": types}
