"""
DerivedFactorEngine — evaluates formula strings from strategy JSON
`derived_factors` array.

Supported syntax:
  Standard arithmetic (+, -, *, /)
  Column references (e.g. sma_20, adjusted_close)
  lag(column, n)  → series.shift(n)
  abs(x)          → element-wise absolute value

Strategy JSON files are trusted configuration; eval() is used with a
restricted builtins dict to prevent accidental name shadowing.
"""
from typing import Dict, List

import numpy as np
import pandas as pd


class FormulaError(Exception):
    pass


class DerivedFactorEngine:

    def compute(self, df: pd.DataFrame, derived_factors: List[Dict]) -> pd.DataFrame:
        """Return a copy of df with all derived factor columns appended."""
        result = df.copy()
        for factor in derived_factors:
            name = factor["name"]
            formula = factor["formula"]
            try:
                result[name] = self._eval(formula, result)
            except Exception as exc:
                raise FormulaError(
                    f"Error computing derived factor '{name}' "
                    f"with formula '{formula}': {exc}"
                ) from exc
        return result

    # ── evaluation ────────────────────────────────────────────────────────────

    def _eval(self, formula: str, df: pd.DataFrame) -> pd.Series:
        namespace: Dict = {col: df[col].copy() for col in df.columns}
        namespace["lag"] = lambda series, n: series.shift(int(n))
        namespace["abs"] = lambda x: x.abs() if hasattr(x, "abs") else abs(x)
        namespace["np"] = np
        return eval(formula, {"__builtins__": {}}, namespace)  # noqa: S307
