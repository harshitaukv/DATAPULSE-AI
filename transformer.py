"""Business transformations applied to cleaned records."""
from __future__ import annotations

import pandas as pd

from app.processing.errors import TransformationError

_SAFE_EXPRESSIONS = {
    "quantity * unit_price": lambda df: (df["quantity"] * df["unit_price"]).round(2),
}


def apply_transformations(clean: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[str]]:
    """Add derived columns. Only whitelisted expressions are supported: no eval of user input."""
    out = clean.copy()
    applied: list[str] = []
    for column, expression in config.get("derived_columns", {}).items():
        fn = _SAFE_EXPRESSIONS.get(expression)
        if fn is None:
            raise TransformationError(f"Derived column '{column}' uses an unsupported expression '{expression}'.",
                                      {"column": column, "expression": expression})
        try:
            out[column] = fn(out) if len(out) else pd.Series(dtype="float64")
        except KeyError as exc:
            raise TransformationError(f"Derived column '{column}' requires missing input column {exc}.",
                                      {"column": column, "missing_input": str(exc)}) from exc
        applied.append(f"Derived {column} = {expression}")
    return out, applied
