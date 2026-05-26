"""
FilterEngine — applies fundamental and technical filters from strategy JSON
to a cross-sectional snapshot DataFrame (one row per ticker).

Value can be:
  - A number  → compared against the field value
  - A string  → treated as a column reference in the same row
  - A 2-list  → [lo, hi] for "between" operator
"""
from typing import Dict, List

import pandas as pd


class FilterError(Exception):
    pass


class FilterEngine:

    def apply(self, snapshot_df: pd.DataFrame, filters_config: Dict) -> pd.DataFrame:
        """Return subset of snapshot_df that passes all filter blocks."""
        result = snapshot_df.copy()

        for block_name in ("fundamental", "technical"):
            block = filters_config.get(block_name, {})
            conditions = block.get("conditions", [])
            if not conditions:
                continue

            logic = block.get("logic", "AND")
            mask = self._build_mask(result, conditions, logic)
            result = result[mask]

        return result

    # ── mask building ─────────────────────────────────────────────────────────

    def _build_mask(
        self, df: pd.DataFrame, conditions: List[Dict], logic: str
    ) -> pd.Series:
        masks = [self._condition_mask(df, cond) for cond in conditions]
        if not masks:
            return pd.Series(True, index=df.index)

        combined = masks[0]
        for m in masks[1:]:
            combined = (combined & m) if logic == "AND" else (combined | m)
        return combined

    def _condition_mask(self, df: pd.DataFrame, cond: Dict) -> pd.Series:
        field = cond["field"]
        op = cond["op"]
        value = cond["value"]

        if field not in df.columns:
            raise FilterError(f"Field '{field}' not found in snapshot DataFrame")

        left = df[field]

        # Value is a column reference
        if isinstance(value, str):
            if value not in df.columns:
                raise FilterError(f"Value reference '{value}' not found in snapshot")
            right = df[value]
        else:
            right = value

        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == "==":
            return left == right
        if op == "between":
            lo, hi = value
            return (left >= lo) & (left <= hi)

        raise FilterError(f"Unknown operator: '{op}'")
