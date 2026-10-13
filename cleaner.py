"""Row-level cleaning: type coercion, constraint checks, quarantine and de-duplication.

Nothing is silently deleted. Every rejected row is written to a quarantine set
with the reason(s) it was rejected, and the original upload is preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class CleaningResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    missing_by_column: dict[str, int] = field(default_factory=dict)
    type_errors_by_column: dict[str, int] = field(default_factory=dict)
    constraint_violations: dict[str, int] = field(default_factory=dict)
    duplicate_records: int = 0
    duplicates_removed: int = 0
    null_business_key: int = 0
    unusual_values: dict[str, int] = field(default_factory=dict)
    transformations: list[str] = field(default_factory=list)


def _missing_mask(series: pd.Series) -> pd.Series:
    as_text = series.astype("string").str.strip()
    return series.isna() | as_text.isna() | (as_text == "") | as_text.str.lower().isin(["null", "none", "nan"])


def clean_dataframe(raw: pd.DataFrame, config: dict) -> CleaningResult:
    columns: dict = config["columns"]
    business_key: list[str] = config.get("business_key", [])
    dedup_policy: str = config.get("dedup_policy", "keep_first")

    df = raw.copy()
    n = len(df)
    reasons = pd.Series([[] for _ in range(n)], index=df.index, dtype=object)
    invalid_flag = pd.Series(False, index=df.index)
    missing_flag = pd.Series(False, index=df.index)
    result = CleaningResult(clean=df, quarantine=df.head(0))
    typed: dict[str, pd.Series] = {}

    def add_reason(mask: pd.Series, text: str):
        for idx in mask[mask].index:
            reasons.at[idx].append(text)

    for name, spec in columns.items():
        if name not in df.columns:
            continue
        series = df[name]
        missing = _missing_mask(series)
        result.missing_by_column[name] = int(missing.sum())
        if spec.get("required", True):
            missing_flag |= missing
            add_reason(missing, f"missing {name}")

        ctype = spec.get("type", "string")
        present = ~missing
        if ctype in ("integer", "float"):
            numeric = pd.to_numeric(series.where(present), errors="coerce")
            bad_type = present & numeric.isna()
            if ctype == "integer":
                non_int = present & numeric.notna() & (numeric % 1 != 0)
                bad_type |= non_int
            typed[name] = numeric
        elif ctype == "date":
            parsed = pd.to_datetime(series.where(present), format="%Y-%m-%d", errors="coerce")
            bad_type = present & parsed.isna()
            typed[name] = parsed
        else:
            typed[name] = series.astype("string").str.strip()
            bad_type = pd.Series(False, index=df.index)
        result.type_errors_by_column[name] = int(bad_type.sum())
        invalid_flag |= bad_type
        add_reason(bad_type, f"invalid {ctype} in {name}")

        valid_vals = present & ~bad_type
        if "min" in spec:
            v = valid_vals & (typed[name] < spec["min"])
            _count(result, f"{name}_below_min", v)
            invalid_flag |= v
            add_reason(v, f"{name} below minimum {spec['min']}")
        if "min_exclusive" in spec:
            v = valid_vals & (typed[name] <= spec["min_exclusive"])
            _count(result, f"{name}_not_positive", v)
            invalid_flag |= v
            add_reason(v, f"{name} must be greater than {spec['min_exclusive']}")
        if "allowed" in spec:
            normalized = typed[name].str.title()
            v = valid_vals & ~normalized.isin(spec["allowed"])
            _count(result, f"{name}_not_allowed", v)
            invalid_flag |= v
            add_reason(v, f"{name} not in allowed set")
            typed[name] = normalized

    # Duplicate analysis on the business key (only rows whose key is present).
    key_cols = [k for k in business_key if k in df.columns]
    key_valid = pd.Series(True, index=df.index)
    for k in key_cols:
        key_valid &= ~_missing_mask(df[k])
    result.null_business_key = int((~key_valid).sum()) if key_cols else 0
    dup_flag = pd.Series(False, index=df.index)
    if key_cols:
        keyed = df.loc[key_valid, key_cols].astype("string").apply(lambda c: c.str.strip())
        dup_flag.loc[key_valid] = keyed.duplicated(keep="first").to_numpy()
        result.duplicate_records = int(dup_flag.sum())

    reject = invalid_flag | missing_flag
    if dedup_policy == "keep_first" and key_cols:
        dedup_mask = dup_flag & ~reject
        add_reason(dedup_mask, "duplicate business key (keep_first policy)")
        result.duplicates_removed = int(dedup_mask.sum())
        reject = reject | dedup_mask
        if result.duplicates_removed:
            result.transformations.append(
                f"De-duplicated on {key_cols} with keep_first: {result.duplicates_removed} rows quarantined")

    clean = pd.DataFrame(index=df.index[~reject])
    for name in columns:
        if name in typed:
            col = typed[name][~reject]
            spec_type = columns[name].get("type")
            if spec_type == "integer":
                col = col.astype("int64")
            elif spec_type == "float":
                col = col.astype("float64").round(4)
            elif spec_type == "date":
                col = col.dt.strftime("%Y-%m-%d")
            clean[name] = col
    clean = clean.reset_index(drop=True)
    result.transformations.append("Converted columns to declared types")
    if any(c.get("allowed") for c in columns.values()):
        result.transformations.append("Normalised categorical values to title case")

    quarantine = raw.loc[reject].copy()
    quarantine.insert(0, "_source_row", quarantine.index.to_numpy() + 1)
    quarantine["_rejection_reasons"] = reasons[reject].map("; ".join)
    result.quarantine = quarantine.reset_index(drop=True)
    result.clean = clean

    # Valid-but-unusual values: kept in the output, reported separately.
    for name, spec in columns.items():
        if spec.get("type") in ("integer", "float") and name in clean.columns and len(clean) > 20:
            vals = clean[name].astype(float)
            med = vals.median()
            mad = float(np.median(np.abs(vals - med))) or 1e-9
            robust_z = 0.6745 * (vals - med) / mad
            result.unusual_values[name] = int((robust_z.abs() > 8).sum())
    return result


def _count(result: CleaningResult, key: str, mask: pd.Series) -> None:
    result.constraint_violations[key] = result.constraint_violations.get(key, 0) + int(mask.sum())
