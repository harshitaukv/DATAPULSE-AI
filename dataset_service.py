"""Dataset (upload) handling."""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import Dataset, User, new_id
from app.ingestion.file_validation import (detect_format, safe_filename, validate_content_sniff,
                                           validate_size)
from app.ingestion.loader import load_dataframe
from app.processing.validator import compare_schema, normalize_headers
from app.security.encryption import read_encrypted, write_encrypted
from app.services.storage import frame_to_records, mask_frame, upload_path


def store_upload(db: Session, filename: str, content: bytes, user: User | None,
                 is_synthetic: bool = False) -> tuple[Dataset, "pd.DataFrame"]:
    settings = get_settings()
    clean_name = safe_filename(filename)
    fmt = detect_format(clean_name)
    validate_size(len(content), settings.max_upload_bytes)
    validate_content_sniff(content, fmt)
    df = load_dataframe(content, fmt)  # raises FileValidationError on bad structure
    dataset_id = new_id()
    stored = f"{dataset_id}.{fmt}.enc"
    write_encrypted(upload_path(stored), content)
    ds = Dataset(id=dataset_id, original_filename=clean_name, stored_filename=stored, file_format=fmt,
                 size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), row_count=len(df),
                 columns=[str(c) for c in df.columns], is_synthetic=is_synthetic or clean_name.startswith("synthetic_"),
                 uploaded_by=user.id if user else None)
    db.add(ds)
    db.commit()
    return ds, df


def read_dataset_bytes(ds: Dataset) -> bytes:
    return read_encrypted(upload_path(ds.stored_filename))


def preview(ds: Dataset, config: dict, rows: int = 20, mask: bool = True) -> dict:
    df = load_dataframe(read_dataset_bytes(ds), ds.file_format)
    normalized, changes = normalize_headers(df)
    schema = compare_schema(list(normalized.columns), config)
    head = df.head(rows)
    if mask:
        head = mask_frame(head, get_settings().sensitive_column_list)
    return {"columns": list(df.columns), "rows": frame_to_records(head), "row_count": len(df),
            "schema_check": schema.to_dict(), "header_normalisation": changes,
            "masked_columns": get_settings().sensitive_column_list if mask else []}
