"""Upload validation: extension, size, filename safety, structure, emptiness."""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePath

ALLOWED_EXTENSIONS = {".csv": "csv", ".json": "json"}
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class FileValidationError(ValueError):
    """Raised when an uploaded file is rejected. The message is safe to show to users."""

    def __init__(self, message: str, code: str = "invalid_file"):
        super().__init__(message)
        self.code = code


def safe_filename(name: str) -> str:
    """Strip directories, control characters and unusual symbols from a client filename."""
    base = PurePath(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = _SAFE_CHARS.sub("_", base).strip("._")
    return (base or "upload")[:120]


def detect_format(filename: str) -> str:
    suffix = PurePath(filename.lower()).suffix
    if suffix not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type '{suffix or 'none'}'. Upload a .csv or .json file.", "unsupported_type")
    return ALLOWED_EXTENSIONS[suffix]


def validate_size(size: int, max_bytes: int) -> None:
    if size == 0:
        raise FileValidationError("The uploaded file is empty.", "empty_file")
    if size > max_bytes:
        raise FileValidationError(
            f"File is {size / 1_048_576:.1f} MB; the limit is {max_bytes / 1_048_576:.0f} MB.", "too_large")


def validate_content_sniff(content: bytes, file_format: str) -> None:
    """Reject binary content masquerading as text."""
    head = content[:4096]
    if b"\x00" in head:
        raise FileValidationError("The file contains binary data and is not valid CSV/JSON text.", "binary")
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head[:-4].decode("utf-8")  # tolerate a multibyte char cut at the boundary
        except UnicodeDecodeError:
            raise FileValidationError("The file is not UTF-8 encoded text.", "encoding")
    stripped = head.lstrip()
    if file_format == "json" and stripped[:1] not in (b"[", b"{"):
        raise FileValidationError("JSON uploads must contain an array of records or an object with a "
                                  "'records' array.", "bad_structure")
