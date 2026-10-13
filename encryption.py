"""Encryption at rest for stored datasets and generated outputs (Fernet: AES-128-CBC + HMAC-SHA256)."""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().data_encryption_key.encode())


def write_encrypted(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fernet().encrypt(data))


def read_encrypted(path: Path) -> bytes:
    try:
        return _fernet().decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError("Stored file could not be decrypted: the encryption key does not match.") from exc
