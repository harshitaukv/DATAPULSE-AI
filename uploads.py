"""Dataset upload, listing, preview and deletion."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import dataset_out, get_or_404
from app.config import get_settings
from app.database.connection import get_db
from app.database.models import Dataset, Pipeline, User
from app.database.seed import DEFAULT_PIPELINE_NAME
from app.ingestion.file_validation import FileValidationError
from app.schemas import UploadResponse
from app.security.audit import record_audit
from app.security.authorization import has_permission, require
from app.services import dataset_service
from app.services.storage import upload_path

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    chunks, total = [], 0
    while chunk := await file.read(1024 * 256):
        total += len(chunk)
        if total > limit:
            raise FileValidationError(f"File exceeds the {limit / 1_048_576:.0f} MB upload limit.", "too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _default_config(db: Session) -> dict:
    p = db.scalar(select(Pipeline).where(Pipeline.name == DEFAULT_PIPELINE_NAME))
    return p.config if p else {"columns": {}}


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_dataset(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(require("upload"))):
    settings = get_settings()
    try:
        declared = int(request.headers.get("content-length", 0))
        if declared > settings.max_upload_bytes + 64 * 1024:
            raise FileValidationError(f"File exceeds the {settings.max_upload_mb:.0f} MB upload limit.", "too_large")
        content = await _read_limited(file, settings.max_upload_bytes)
        ds, _ = dataset_service.store_upload(db, file.filename or "upload", content, user)
    except FileValidationError as exc:
        record_audit(db, "upload_dataset", user=user, resource_type="dataset", outcome="rejected",
                     details={"filename": (file.filename or "")[:120], "reason": exc.code}, request=request)
        raise HTTPException(status_code=413 if exc.code == "too_large" else 422, detail=str(exc))
    record_audit(db, "upload_dataset", user=user, resource_type="dataset", resource_id=ds.id,
                 details={"filename": ds.original_filename, "rows": ds.row_count, "bytes": ds.size_bytes},
                 request=request)
    preview = dataset_service.preview(ds, _default_config(db), mask=True)
    return UploadResponse(dataset=dataset_out(ds), preview=preview)


@router.get("")
def list_datasets(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _: User = Depends(require("read"))):
    q = select(Dataset).where(Dataset.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(Dataset.uploaded_at.desc()).offset(offset).limit(limit))
    return {"items": [dataset_out(d) for d in items], "total": total, "limit": limit, "offset": offset}


@router.get("/{dataset_id}/preview")
def preview_dataset(dataset_id: str, rows: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
                    user: User = Depends(require("read"))):
    ds = get_or_404(db, Dataset, dataset_id, "Dataset")
    if ds.deleted_at:
        raise HTTPException(410, "Dataset has been deleted under the retention policy.")
    unmasked = has_permission(user, "download_records") and (ds.uploaded_by == user.id or user.role == "admin")
    return dataset_service.preview(ds, _default_config(db), rows=rows, mask=not unmasked)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(require("delete_data"))):
    ds = get_or_404(db, Dataset, dataset_id, "Dataset")
    upload_path(ds.stored_filename).unlink(missing_ok=True)
    ds.deleted_at = datetime.now(timezone.utc)
    db.commit()
    record_audit(db, "delete_dataset", user=admin, resource_type="dataset", resource_id=ds.id,
                 details={"filename": ds.original_filename}, request=request)
