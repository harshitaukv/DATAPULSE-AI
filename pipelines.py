"""Pipelines and runs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, run_summary
from app.config import get_settings
from app.database.connection import get_db
from app.database.models import Dataset, Pipeline, PipelineRun, User
from app.schemas import PipelineCreate, PipelineOut, RunDetail, RunRequest
from app.security.audit import record_audit
from app.security.authorization import has_permission, require
from app.services import pipeline_service, storage

router = APIRouter(prefix="/api/v1", tags=["pipelines"])


def can_access_records(user: User, run: PipelineRun) -> bool:
    """Unmasked record-level data: administrators, or the engineer who triggered the run."""
    return user.role == "admin" or (has_permission(user, "download_records") and run.triggered_by == user.id)


@router.get("/pipelines", response_model=list[PipelineOut])
def list_pipelines(db: Session = Depends(get_db), _: User = Depends(require("read"))):
    return list(db.scalars(select(Pipeline).order_by(Pipeline.id)))


@router.post("/pipelines", response_model=PipelineOut, status_code=201)
def create_pipeline(body: PipelineCreate, request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(require("manage_pipelines"))):
    cols = body.config.get("columns")
    if not isinstance(cols, dict) or not cols:
        raise HTTPException(422, "config.columns must declare at least one column.")
    for name, spec in cols.items():
        if spec.get("type", "string") not in ("string", "integer", "float", "date"):
            raise HTTPException(422, f"Column '{name}' has an unsupported type.")
    if db.scalar(select(Pipeline).where(Pipeline.name == body.name)):
        raise HTTPException(409, "A pipeline with that name already exists.")
    p = Pipeline(name=body.name, description=body.description, source_type=body.source_type,
                 config=body.config, created_by=admin.id)
    db.add(p)
    db.commit()
    record_audit(db, "create_pipeline", user=admin, resource_type="pipeline", resource_id=p.id, request=request)
    return p


@router.get("/pipelines/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db), _: User = Depends(require("read"))):
    return get_or_404(db, Pipeline, pipeline_id, "Pipeline")


@router.post("/pipelines/{pipeline_id}/runs", response_model=RunDetail, status_code=201)
def start_run(pipeline_id: int, body: RunRequest, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require("run_pipeline"))):
    pipeline = get_or_404(db, Pipeline, pipeline_id, "Pipeline")
    if pipeline.status != "active":
        raise HTTPException(409, "Pipeline is inactive.")
    dataset = get_or_404(db, Dataset, body.dataset_id, "Dataset")
    if dataset.deleted_at:
        raise HTTPException(410, "Dataset has been deleted.")
    options = {}
    if body.fault_injection:
        if not get_settings().enable_fault_injection:
            raise HTTPException(403, "Failure simulation is disabled in this environment.")
        if not has_permission(user, "fault_injection"):
            raise HTTPException(403, "Your role cannot use failure simulation.")
        options["fault_injection"] = body.fault_injection.model_dump()
    run = pipeline_service.run_pipeline(db, pipeline, dataset, user, options=options)
    record_audit(db, "run_pipeline", user=user, resource_type="pipeline_run", resource_id=run.id,
                 outcome="success" if run.status != "failed" else "failure",
                 details={"pipeline": pipeline.name, "dataset": dataset.original_filename, "status": run.status,
                          "simulated_fault": bool(options.get("fault_injection"))}, request=request)
    return run_summary(db, run, detail=True)


@router.get("/runs")
def list_runs(pipeline_id: int | None = None, status: str | None = None,
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), _: User = Depends(require("read"))):
    q = select(PipelineRun)
    if pipeline_id:
        q = q.where(PipelineRun.pipeline_id == pipeline_id)
    if status:
        q = q.where(PipelineRun.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    runs = pipeline_service.list_runs(db, pipeline_id, status, limit, offset)
    return {"items": [run_summary(db, r) for r in runs], "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db), _: User = Depends(require("read"))):
    return run_summary(db, get_or_404(db, PipelineRun, run_id, "Run"), detail=True)


@router.get("/runs/{run_id}/quality")
def run_quality(run_id: str, quarantine_rows: int = Query(25, ge=0, le=200), db: Session = Depends(get_db),
                user: User = Depends(require("read"))):
    run = get_or_404(db, PipelineRun, run_id, "Run")
    report = run.report or {}
    sample = []
    if run.quarantine_filename and quarantine_rows:
        df = storage.load_frame(run.quarantine_filename).head(quarantine_rows)
        if not can_access_records(user, run):
            df = storage.mask_frame(df, get_settings().sensitive_column_list)
        sample = storage.frame_to_records(df)
    return {"run_id": run.id, "status": run.status, "quality_score": run.quality_score,
            "metrics": run.metrics, "checks": report.get("checks", []), "schema": report.get("schema"),
            "findings": report.get("findings", []), "quarantine_summary": report.get("quarantine_summary", {}),
            "transformations": report.get("transformations", []), "baseline": report.get("baseline"),
            "anomaly_detection": run.anomaly, "quarantine_sample": sample,
            "records_masked": not can_access_records(user, run),
            "masked_columns": get_settings().sensitive_column_list}


@router.get("/runs/{run_id}/download/{kind}")
def download_run_file(run_id: str, kind: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("read"))):
    run = get_or_404(db, PipelineRun, run_id, "Run")
    if kind == "report":
        import json
        body = json.dumps({"run": run_summary(db, run, detail=True).model_dump(mode="json")}, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="quality_report_{run.id[:8]}.json"'})
    if kind not in ("processed", "quarantine"):
        raise HTTPException(404, "Unknown file type. Use processed, quarantine or report.")
    if not can_access_records(user, run):
        raise HTTPException(403, "Record-level data is available to the engineer who ran the pipeline "
                                 "and to administrators.")
    filename = run.processed_filename if kind == "processed" else run.quarantine_filename
    if not filename:
        raise HTTPException(404, f"This run has no {kind} file.")
    record_audit(db, f"download_{kind}", user=user, resource_type="pipeline_run", resource_id=run.id, request=request)
    return Response(storage.read_bytes(filename), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{kind}_{run.id[:8]}.csv"'})
