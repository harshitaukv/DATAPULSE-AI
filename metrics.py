"""Data-quality metrics, the quality score, and monitoring features.

Quality score (0-100) =
    100 * (0.30 * completeness + 0.25 * uniqueness + 0.35 * validity + 0.10 * schema_conformance)

  completeness       = 1 - rows missing at least one required value / rows
  uniqueness         = 1 - duplicate business-key rows / rows
  validity           = 1 - rows with type or constraint violations / rows
  schema_conformance = 1.0 if the schema matches exactly, 0.5 if columns had to be mapped or extra
                       columns were present
"""
from __future__ import annotations

import math

FEATURE_NAMES = ["log_input_records", "missing_rows_pct", "duplicate_pct", "invalid_pct",
                 "duration_seconds", "record_count_deviation"]

WEIGHTS = {"completeness": 0.30, "uniqueness": 0.25, "validity": 0.35, "schema_conformance": 0.10}


def compute_quality_metrics(*, input_records: int, cleaning, schema_report, required_columns: list[str],
                            output_records: int) -> dict:
    rows = max(input_records, 1)
    req_cells = rows * max(len(required_columns), 1)
    missing_required = sum(cleaning.missing_by_column.get(c, 0) for c in required_columns)
    type_errors = sum(cleaning.type_errors_by_column.values())
    constraint = sum(cleaning.constraint_violations.values())
    quarantined = len(cleaning.quarantine)
    invalid_rows = int((cleaning.quarantine["_rejection_reasons"]
                        .str.contains("invalid|below minimum|greater than|not in allowed", regex=True)).sum()) \
        if quarantined else 0

    rows_missing = int(cleaning.quarantine["_rejection_reasons"].str.contains("missing ", regex=False).sum()) \
        if quarantined else 0
    completeness = 1 - rows_missing / rows
    uniqueness = 1 - cleaning.duplicate_records / rows
    validity = 1 - invalid_rows / rows
    conformance = 1.0 if schema_report.conforms else 0.5
    components = {"completeness": completeness, "uniqueness": uniqueness,
                  "validity": validity, "schema_conformance": conformance}
    score = 100 * sum(WEIGHTS[k] * max(0.0, v) for k, v in components.items())
    return {
        "input_records": input_records,
        "output_records": output_records,
        "quarantined_records": quarantined,
        "missing_cells_required": missing_required,
        "rows_with_missing_required": rows_missing,
        "missing_rows_pct": round(100 * rows_missing / rows, 4),
        "missing_pct": round(100 * missing_required / req_cells, 4),
        "missing_by_column": cleaning.missing_by_column,
        "duplicate_records": cleaning.duplicate_records,
        "duplicates_removed": cleaning.duplicates_removed,
        "duplicate_pct": round(100 * cleaning.duplicate_records / rows, 4),
        "invalid_records": invalid_rows,
        "invalid_pct": round(100 * invalid_rows / rows, 4),
        "type_errors_by_column": cleaning.type_errors_by_column,
        "type_errors_total": type_errors,
        "constraint_violations": cleaning.constraint_violations,
        "constraint_violations_total": constraint,
        "null_business_key": cleaning.null_business_key,
        "unusual_values": cleaning.unusual_values,
        "quality_components": {k: round(v, 4) for k, v in components.items()},
        "quality_score": round(score, 2),
    }


def feature_vector(metrics: dict, duration: float, deviation: float) -> list[float]:
    return [math.log10(max(metrics.get("input_records", 0), 1)),
            float(metrics.get("missing_rows_pct", 0.0)),
            float(metrics.get("duplicate_pct", 0.0)),
            float(metrics.get("invalid_pct", 0.0)),
            float(duration),
            float(deviation)]
