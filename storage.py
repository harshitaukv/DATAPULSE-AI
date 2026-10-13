"""Encrypted file storage for uploads and pipeline outputs.

Files are addressed by server-generated names only; client filenames are never
used as paths, and paths are never returned through the API.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.security.encryption import read_encrypted, write_encrypted


def upload_path(stored_filename: str) -> Path:
    return get_settings().uploads_dir / stored_filename


def processed_path(filename: str) -> Path:
    return get_settings().processed_dir / filename


def save_frame(df: pd.DataFrame, filename: str) -> None:
    write_encrypted(processed_path(filename), df.to_csv(index=False).encode())


def load_frame(filename: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(read_encrypted(processed_path(filename))), dtype=str,
                       keep_default_na=False, na_values=[""])


def read_bytes(filename: str) -> bytes:
    return read_encrypted(processed_path(filename))


def mask_value(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return value
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def mask_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(mask_value).astype(object)
    return out


def frame_to_records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
