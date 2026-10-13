"""Parse CSV/JSON bytes into a DataFrame of raw strings.

All values are loaded as strings so that type validation happens explicitly in
the processing layer, where every conversion failure is recorded as evidence.
Uploaded content is only ever parsed as data, never executed.
"""
from __future__ import annotations

import csv
import io
import json

import pandas as pd

from app.ingestion.file_validation import FileValidationError


def load_dataframe(content: bytes, file_format: str) -> pd.DataFrame:
    if file_format == "csv":
        df = _load_csv(content)
    elif file_format == "json":
        df = _load_json(content)
    else:  # pragma: no cover - guarded by detect_format
        raise FileValidationError(f"Unsupported format {file_format}", "unsupported_type")
    if df.shape[1] == 0:
        raise FileValidationError("No columns were found in the file.", "no_columns")
    if len(df) == 0:
        raise FileValidationError("The file has a header but no data rows.", "empty_dataset")
    return df


def _load_csv(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8-sig", errors="replace")
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""],
                         skip_blank_lines=True, on_bad_lines="error", engine="python")
    except pd.errors.EmptyDataError:
        raise FileValidationError("The CSV file contains no data.", "empty_dataset")
    except (pd.errors.ParserError, csv.Error) as exc:
        raise FileValidationError(f"The CSV structure is malformed: {str(exc).splitlines()[0][:200]}",
                                  "malformed_csv")
    df.columns = [str(c) for c in df.columns]
    if any(c.startswith("Unnamed:") for c in df.columns):
        raise FileValidationError("The CSV header contains empty column names.", "bad_header")
    return df


def _load_json(content: bytes) -> pd.DataFrame:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FileValidationError(f"The JSON is malformed or truncated ({exc.msg if hasattr(exc, 'msg') else exc}).",
                                  "malformed_json")
    if isinstance(payload, dict):
        payload = payload.get("records", payload.get("data"))
    if not isinstance(payload, list):
        raise FileValidationError("JSON must be an array of records or an object with a 'records' array.",
                                  "bad_structure")
    if not payload:
        raise FileValidationError("The JSON array contains no records.", "empty_dataset")
    if not all(isinstance(r, dict) for r in payload):
        raise FileValidationError("Every JSON record must be an object.", "bad_structure")
    df = pd.DataFrame.from_records(payload)
    # Convert to raw strings while keeping genuine nulls as missing.
    return df.apply(lambda col: col.map(lambda v: None if v is None or (isinstance(v, float) and v != v)
                                        else str(v))).astype(object)
