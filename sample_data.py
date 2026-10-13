"""Synthetic sales data generator.

All data produced here is SYNTHETIC: identifiers, customers and amounts are
random values generated from a fixed seed. It is used for demonstrations,
baselines and evaluation only.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

REGIONS = ["North", "South", "East", "West", "Central"]
COLUMNS = ["transaction_id", "customer_id", "product_id", "quantity", "unit_price",
           "transaction_date", "region"]


def generate_clean(n_rows: int = 5000, seed: int = 7, day: date | None = None,
                   id_prefix: str = "T") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    day = day or date(2026, 9, 1)
    quantities = rng.integers(1, 12, n_rows)
    prices = np.round(rng.gamma(2.2, 18.0, n_rows) + 1.5, 2)
    return pd.DataFrame({
        "transaction_id": [f"{id_prefix}{seed:04d}-{i:07d}" for i in range(n_rows)],
        "customer_id": [f"C{x:06d}" for x in rng.integers(1, 40_000, n_rows)],
        "product_id": [f"P{x:04d}" for x in rng.integers(1, 800, n_rows)],
        "quantity": quantities,
        "unit_price": prices,
        "transaction_date": [day.isoformat()] * n_rows,
        "region": rng.choice(REGIONS, n_rows, p=[0.24, 0.22, 0.2, 0.2, 0.14]),
    })


def inject_missing_and_duplicates(df: pd.DataFrame, seed: int = 11, missing_frac: float = 0.30,
                                  dup_frac: float = 0.06) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.copy().astype(object)
    n = len(out)
    for col in ["customer_id", "unit_price", "region", "quantity"]:
        idx = rng.choice(n, int(n * missing_frac / 4), replace=False)
        out.loc[idx, col] = None
    dups = out.sample(frac=dup_frac, random_state=seed)
    return pd.concat([out, dups], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)


def inject_invalid_and_schema_change(df: pd.DataFrame, seed: int = 13, n_keep: int = 420) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.head(n_keep).copy().astype(object)
    n = len(out)
    idx = rng.choice(n, 30, replace=False)
    out.loc[idx[:10], "quantity"] = [-int(x) for x in rng.integers(1, 5, 10)]
    out.loc[idx[10:18], "unit_price"] = "N/A"
    out.loc[idx[18:24], "unit_price"] = 0
    out.loc[idx[24:27], "transaction_date"] = "2026-13-45"
    out.loc[idx[27:30], "region"] = "Atlantis"
    out = out.rename(columns={"customer_id": "cust_id"})
    out["discount_code"] = rng.choice(["", "AUTUMN10", "VIP5"], n)
    return out


def truncate_rows(df: pd.DataFrame) -> bytes:
    """Return CSV bytes whose final row is cut off mid-record, imitating an interrupted transfer."""
    text = df.to_csv(index=False)
    last_newline = text.rstrip("\n").rfind("\n")
    last_line = text[last_newline + 1:].rstrip("\n")
    return (text[:last_newline + 1] + last_line[: max(8, len(last_line) // 3)] + "\n").encode()


@dataclass(frozen=True)
class SampleSpec:
    filename: str
    description: str


SAMPLES = [
    SampleSpec("synthetic_sales_clean.csv", "Clean sales data (5,000 rows)."),
    SampleSpec("synthetic_sales_clean.json", "Clean sales data as JSON (1,000 rows)."),
    SampleSpec("synthetic_sales_missing_duplicates.csv", "Missing values and duplicate transactions."),
    SampleSpec("synthetic_sales_invalid_schema_change.csv",
               "Renamed column (customer_id -> cust_id), new column, invalid values and an abnormally low "
               "record count (420 rows)."),
    SampleSpec("synthetic_sales_low_volume.csv", "Valid schema but only 300 rows (volume anomaly)."),
    SampleSpec("synthetic_sales_truncated.csv", "File cut off mid-record (incomplete delivery)."),
    SampleSpec("synthetic_sales_corrected.csv",
               "Corrected re-delivery for the schema-change scenario (5,000 clean rows)."),
]


def build_sample(filename: str) -> bytes:
    base = generate_clean(5000, seed=7)
    if filename == "synthetic_sales_clean.csv":
        return base.to_csv(index=False).encode()
    if filename == "synthetic_sales_clean.json":
        return json.dumps(generate_clean(1000, seed=8).to_dict(orient="records"), indent=1).encode()
    if filename == "synthetic_sales_missing_duplicates.csv":
        return inject_missing_and_duplicates(generate_clean(5000, seed=9)).to_csv(index=False).encode()
    if filename == "synthetic_sales_invalid_schema_change.csv":
        return inject_invalid_and_schema_change(generate_clean(5000, seed=10)).to_csv(index=False).encode()
    if filename == "synthetic_sales_low_volume.csv":
        return generate_clean(300, seed=12).to_csv(index=False).encode()
    if filename == "synthetic_sales_truncated.csv":
        return truncate_rows(generate_clean(4800, seed=14))
    if filename == "synthetic_sales_corrected.csv":
        return generate_clean(5000, seed=15).to_csv(index=False).encode()
    raise KeyError(filename)


def generate_all(target_dir) -> list[str]:
    from pathlib import Path
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in SAMPLES:
        (target / spec.filename).write_bytes(build_sample(spec.filename))
        written.append(spec.filename)
    return written


def daily_history_frames(days: int = 14, start: date = date(2026, 9, 1), seed: int = 100):
    """Clean daily batches with natural volume variation, used to build an initial baseline."""
    rng = np.random.default_rng(seed)
    for d in range(days):
        n = int(rng.normal(5000, 220))
        yield start + timedelta(days=d), generate_clean(n, seed=seed + d, day=start + timedelta(days=d), id_prefix="H")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()
