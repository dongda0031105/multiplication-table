"""
UniverseFilter — applies universe and fundamental filters from strategy JSON.

Usage:
    uf = UniverseFilter()
    passed = uf.filter_by_universe(tickers_with_fundamentals, strategy["universe"])
    passed = uf.filter_by_fundamentals(passed, strategy["filters"]["fundamental"]["conditions"])
"""
from typing import Any, Dict, List


class UniverseFilter:

    # ── Universe-level filters ────────────────────────────────────────────────

    def filter_by_universe(
        self,
        tickers: List[Dict],
        universe_config: Dict,
    ) -> List[Dict]:
        """
        Filter by: min_price, min_market_cap, min_avg_volume_20d,
        exclude_sectors, include_symbols, exclude_symbols.
        """
        min_price = universe_config.get("min_price", 0)
        min_mkt_cap = universe_config.get("min_market_cap", 0)
        min_vol = universe_config.get("min_avg_volume_20d", 0)
        exclude_sectors = set(universe_config.get("exclude_sectors", []))
        include_symbols = set(universe_config.get("include_symbols", []))
        exclude_symbols = set(universe_config.get("exclude_symbols", []))

        result: List[Dict] = []
        for t in tickers:
            ticker = t.get("ticker", "")

            if ticker in exclude_symbols:
                continue

            if include_symbols and ticker in include_symbols:
                result.append(t)
                continue

            if t.get("sector", "") in exclude_sectors:
                continue

            if (t.get("market_cap") or 0) < min_mkt_cap:
                continue

            if (t.get("avg_volume_20d") or 0) < min_vol:
                continue

            if min_price > 0 and (t.get("price") or 0) < min_price:
                continue

            result.append(t)

        return result

    # ── Fundamental-level filters ─────────────────────────────────────────────

    def filter_by_fundamentals(
        self,
        tickers: List[Dict],
        conditions: List[Dict],
    ) -> List[Dict]:
        """
        Apply fundamental filter conditions from strategy JSON.
        Each condition: {"field": "roe", "op": ">", "value": 0.1}
        Supported ops: >, >=, <, <=, ==, between
        Tickers with None / missing field values are excluded.
        """
        return [t for t in tickers if self._passes_all(t, conditions)]

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _passes_all(t: Dict, conditions: List[Dict]) -> bool:
        for cond in conditions:
            field = cond["field"]
            op = cond["op"]
            value = cond["value"]
            field_val = t.get(field)

            if field_val is None:
                return False  # exclude on missing data

            if not UniverseFilter._apply_op(field_val, op, value):
                return False

        return True

    @staticmethod
    def _apply_op(field_val: Any, op: str, value: Any) -> bool:
        if op == ">":
            return field_val > value
        if op == ">=":
            return field_val >= value
        if op == "<":
            return field_val < value
        if op == "<=":
            return field_val <= value
        if op == "==":
            return field_val == value
        if op == "between":
            lo, hi = value
            return lo <= field_val <= hi
        raise ValueError(f"Unknown operator: '{op}'")
