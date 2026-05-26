"""
SignalEngine — generates entry / exit signals from strategy JSON.

Entry logic: AND of all conditions in entry_signals.conditions
Exit logic:  OR  of all conditions in exit_signals.conditions

Condition types handled:
  rank_in_top_n          — ticker rank <= n
  rank_falls_below       — ticker rank > threshold
  crosses_above / below  — MA crossover within lookback_bars
  stop_loss              — ATR-multiple stop
  trailing_stop          — trailing percentage stop
  take_profit            — percentage profit target
  field/op/value         — direct comparison (value can be a column name)

RiskGuard halts new entries when portfolio drawdown exceeds the threshold
defined in strategy risk_management.halt_new_entries_when_drawdown_pct_exceeds.
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# RiskGuard
# ─────────────────────────────────────────────────────────────────────────────

class RiskGuard:
    """Tracks peak NAV and blocks new entries when drawdown exceeds threshold."""

    def __init__(self, halt_drawdown_pct: float = 0.10):
        self.halt_drawdown_pct = halt_drawdown_pct
        self._peak_nav: Optional[float] = None

    def update_nav(self, current_nav: float) -> None:
        if self._peak_nav is None or current_nav > self._peak_nav:
            self._peak_nav = current_nav

    def current_drawdown(self, current_nav: float) -> float:
        if not self._peak_nav:
            return 0.0
        return (self._peak_nav - current_nav) / self._peak_nav

    def is_halted(self, current_nav: float) -> bool:
        return self.current_drawdown(current_nav) >= self.halt_drawdown_pct


# ─────────────────────────────────────────────────────────────────────────────
# SignalEngine
# ─────────────────────────────────────────────────────────────────────────────

class SignalEngine:

    # ── Entry signals ─────────────────────────────────────────────────────────

    def entry_signals(
        self,
        ranked_snapshot: pd.DataFrame,
        histories: Dict[str, pd.DataFrame],
        entry_config: Dict,
        risk_guard: Optional[RiskGuard] = None,
        current_nav: float = 0.0,
    ) -> List[str]:
        """
        Return list of tickers that have valid entry signals.
        If risk_guard is active (halted), returns [] for new entries.
        """
        if risk_guard is not None and risk_guard.is_halted(current_nav):
            return []

        logic = entry_config.get("logic", "AND")
        conditions = entry_config.get("conditions", [])
        results: List[str] = []

        ticker_col = "ticker" if "ticker" in ranked_snapshot.columns else None

        for _, row in ranked_snapshot.iterrows():
            ticker = row[ticker_col] if ticker_col else row.name
            history = histories.get(ticker, pd.DataFrame())
            rank = int(row.get("rank", 9999))

            if self._eval_all(conditions, logic, row.to_dict(), history, rank, None):
                results.append(ticker)

        return results

    # ── Exit signals ──────────────────────────────────────────────────────────

    def exit_signals(
        self,
        ranked_snapshot: pd.DataFrame,
        histories: Dict[str, pd.DataFrame],
        positions: Dict[str, Dict],
        exit_config: Dict,
    ) -> Dict[str, str]:
        """
        Return {ticker: reason} for positions that should be closed.
        Positions not present in ranked_snapshot get rank=9999 (force exit).
        """
        logic = exit_config.get("logic", "OR")
        conditions = exit_config.get("conditions", [])

        ticker_col = "ticker" if "ticker" in ranked_snapshot.columns else None
        snapshot_by_ticker: Dict[str, dict] = {}
        for _, row in ranked_snapshot.iterrows():
            t = row[ticker_col] if ticker_col else row.name
            snapshot_by_ticker[t] = row.to_dict()

        results: Dict[str, str] = {}
        for ticker, position in positions.items():
            row = snapshot_by_ticker.get(ticker, {})
            rank = int(row.get("rank", 9999))
            history = histories.get(ticker, pd.DataFrame())

            triggered, reason = self._eval_exit(conditions, logic, row, history, rank, position)
            if triggered:
                results[ticker] = reason

        return results

    # ── Top-10 output ─────────────────────────────────────────────────────────

    def generate_top10(self, ranked_df: pd.DataFrame) -> List[Dict]:
        """Return top-10 tickers (or fewer if not enough) with key metrics."""
        top = ranked_df.nsmallest(10, "rank") if len(ranked_df) >= 10 else ranked_df
        result: List[Dict] = []
        ticker_col = "ticker" if "ticker" in top.columns else None
        for _, row in top.iterrows():
            ticker = row[ticker_col] if ticker_col else row.name
            result.append({
                "ticker": ticker,
                "rank": int(row.get("rank", 0)),
                "score": round(float(row.get("score", 0)), 2),
                "pe_ratio": row.get("pe_ratio"),
                "adjusted_close": row.get("adjusted_close"),
                "momentum_90d": row.get("momentum_90d"),
            })
        return result

    # ── condition evaluators ──────────────────────────────────────────────────

    def _eval_all(
        self,
        conditions: List[Dict],
        logic: str,
        row: dict,
        history: pd.DataFrame,
        rank: int,
        position: Optional[Dict],
    ) -> bool:
        if not conditions:
            return False
        results = [
            self._eval_one(cond, row, history, rank, position)
            for cond in conditions
        ]
        return all(results) if logic == "AND" else any(results)

    def _eval_exit(
        self,
        conditions: List[Dict],
        logic: str,
        row: dict,
        history: pd.DataFrame,
        rank: int,
        position: Dict,
    ) -> Tuple[bool, str]:
        for cond in conditions:
            if self._eval_one(cond, row, history, rank, position):
                return True, _condition_label(cond)
        return False, ""

    def _eval_one(
        self,
        cond: Dict,
        row: dict,
        history: pd.DataFrame,
        rank: int,
        position: Optional[Dict],
    ) -> bool:
        ctype = cond.get("type")

        # ── rank conditions ───
        if ctype == "rank_in_top_n":
            return rank <= int(cond["n"])
        if ctype == "rank_falls_below":
            return rank > int(cond["rank"])

        # ── crossover conditions ──
        if ctype == "crosses_above":
            return _crosses(history, cond["left"], cond["right"],
                            cond.get("lookback_bars", 3), direction="above")
        if ctype == "crosses_below":
            return _crosses(history, cond["left"], cond["right"],
                            cond.get("lookback_bars", 3), direction="below")

        # ── position-based exits (need position) ──
        if ctype == "stop_loss" and position:
            return _check_stop_loss(cond, row, position)
        if ctype == "trailing_stop" and position:
            return _check_trailing_stop(cond, row, position)
        if ctype == "take_profit" and position:
            return _check_take_profit(cond, row, position)

        # ── field comparison ──
        field = cond.get("field")
        op = cond.get("op")
        value = cond.get("value")
        if field and op:
            field_val = row.get(field)
            if field_val is None:
                return False
            # value may be a column reference
            if isinstance(value, str):
                value = row.get(value)
                if value is None:
                    return False
            return _compare(field_val, op, value)

        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _crosses(
    df: pd.DataFrame, left: str, right: str, lookback: int, direction: str
) -> bool:
    """Check if left crossed above/below right within the last `lookback` bars."""
    if df.empty or left not in df.columns or right not in df.columns:
        return False
    n = len(df)
    if n < 2:
        return False
    start = max(0, n - lookback - 1)
    for i in range(start, n - 1):
        l0, l1 = df[left].iloc[i], df[left].iloc[i + 1]
        r0, r1 = df[right].iloc[i], df[right].iloc[i + 1]
        if direction == "above" and l0 <= r0 and l1 > r1:
            return True
        if direction == "below" and l0 >= r0 and l1 < r1:
            return True
    return False


def _check_stop_loss(cond: Dict, row: dict, position: Dict) -> bool:
    mode = cond.get("mode", "atr_multiple")
    if mode == "atr_multiple":
        atr_field = cond.get("atr", "atr_14")
        multiple = float(cond.get("multiple", 2.0))
        current_price = row.get("adjusted_close", 0)
        entry_price = position.get("entry_price", 0)
        entry_atr = position.get("entry_atr", row.get(atr_field, 0))
        stop_level = entry_price - multiple * entry_atr
        return current_price <= stop_level
    return False


def _check_trailing_stop(cond: Dict, row: dict, position: Dict) -> bool:
    pct = float(cond.get("pct", 0.10))
    current_price = row.get("adjusted_close", 0)
    peak_price = position.get("peak_price", position.get("entry_price", 0))
    stop_level = peak_price * (1.0 - pct)
    return current_price <= stop_level


def _check_take_profit(cond: Dict, row: dict, position: Dict) -> bool:
    pct = float(cond.get("pct", 0.25))
    current_price = row.get("adjusted_close", 0)
    entry_price = position.get("entry_price", 0)
    target = entry_price * (1.0 + pct)
    return current_price >= target


def _compare(field_val, op: str, value) -> bool:
    if op == ">":  return field_val > value
    if op == ">=": return field_val >= value
    if op == "<":  return field_val < value
    if op == "<=": return field_val <= value
    if op == "==": return field_val == value
    if op == "between":
        lo, hi = value
        return lo <= field_val <= hi
    return False


def _condition_label(cond: Dict) -> str:
    ctype = cond.get("type")
    if ctype:
        return ctype
    return f"{cond.get('field','?')} {cond.get('op','?')} {cond.get('value','?')}"
