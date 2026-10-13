"""Schema and structural validation."""
from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field

import pandas as pd

_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalize_column_name(name: str) -> str:
    return _NON_WORD.sub("_", str(name).strip().lower()).strip("_")


@dataclass
class SchemaReport:
    expected_columns: list[str]
    actual_columns: list[str]
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    unexpected_columns: list[str] = field(default_factory=list)
    suggested_mappings: dict[str, dict] = field(default_factory=dict)
    renamed_by_normalization: dict[str, str] = field(default_factory=dict)

    @property
    def conforms(self) -> bool:
        return not self.missing_required and not self.unexpected_columns

    def to_dict(self) -> dict:
        data = asdict(self)
        data["conforms"] = self.conforms
        return data


def normalize_headers(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    mapping = {c: normalize_column_name(c) for c in df.columns}
    changed = {orig: new for orig, new in mapping.items() if orig != new}
    out = df.rename(columns=mapping)
    if out.columns.duplicated().any():
        dupes = sorted(set(out.columns[out.columns.duplicated()]))
        raise ValueError(f"Column names collide after normalisation: {dupes}")
    return out, changed


def compare_schema(actual: list[str], config: dict) -> SchemaReport:
    columns = config["columns"]
    expected = list(columns)
    report = SchemaReport(expected_columns=expected, actual_columns=list(actual))
    actual_set = set(actual)
    for name, spec in columns.items():
        if name not in actual_set:
            (report.missing_required if spec.get("required", True) else report.missing_optional).append(name)
    report.unexpected_columns = [c for c in actual if c not in columns]
    for missing in report.missing_required + report.missing_optional:
        best, best_score = None, 0.0
        for candidate in report.unexpected_columns:
            score = _name_similarity(missing, candidate)
            if score > best_score:
                best, best_score = candidate, score
        if best is not None and best_score >= 0.6:
            report.suggested_mappings[best] = {"maps_to": missing, "similarity": round(best_score, 3)}
    return report


def _name_similarity(a: str, b: str) -> float:
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    # Abbreviation heuristic: cust_id vs customer_id share prefix and suffix tokens.
    ta, tb = a.split("_"), b.split("_")
    if len(ta) == len(tb) and all(x.startswith(y) or y.startswith(x) for x, y in zip(ta, tb)):
        ratio = max(ratio, 0.85)
    return ratio


def detect_truncation(raw: pd.DataFrame, missing_fraction: float = 0.5) -> dict | None:
    """Flag a final row that is mostly empty while the rest of the file is well populated.

    This pattern is typical of a file that was cut off during transfer.
    """
    if len(raw) < 3:
        return None
    last = raw.iloc[-1]
    last_missing = float(last.isna().mean())
    body_missing = float(raw.iloc[:-1].isna().mean().mean())
    if last_missing >= missing_fraction and body_missing < missing_fraction / 2:
        return {"last_row_index": int(len(raw) - 1), "last_row_missing_fraction": round(last_missing, 3),
                "body_missing_fraction": round(body_missing, 4),
                "last_row_populated_values": {k: v for k, v in last.items() if pd.notna(v)}}
    return None
