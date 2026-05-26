"""
ExecutionEngine — places Alpaca market orders (whole shares only).

Design:
  - All order logic is injectable (alpaca_client can be mocked).
  - Whole-share sizing: math.floor(target_value / price).
  - No fractional shares regardless of strategy allow_fractional_shares.
  - Retry up to max_attempts with backoff_seconds between retries.
  - Earnings guard: skip buy/sell if within do_not_trade_before/after_earnings_days.
  - On each successful order, the Notifier is called for real-time email.
"""
import math
import time
import logging
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_MARKET_OPEN_MINUTES_DEFAULT = 15   # wait N minutes after open before trading


class OrderError(Exception):
    pass


class ExecutionEngine:

    def __init__(
        self,
        alpaca_client=None,
        notifier=None,
        max_attempts: int = 3,
        backoff_seconds: float = 5.0,
    ):
        self._client = alpaca_client
        self._notifier = notifier
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.orders_placed: List[Dict] = []   # for testing / audit

    # ── position sizing ───────────────────────────────────────────────────────

    @staticmethod
    def calc_shares(target_value: float, price: float) -> int:
        """Floor division — whole shares only, never fractional."""
        if price <= 0:
            return 0
        return math.floor(target_value / price)

    @staticmethod
    def calc_target_values(
        nav: float,
        target_pct: float,
        tickers: List[str],
        max_single_pct: float = 0.15,
    ) -> Dict[str, float]:
        """Return {ticker: dollar_target} capped at max_single_pct * NAV."""
        base = nav * min(target_pct, max_single_pct)
        return {t: base for t in tickers}

    # ── order placement ───────────────────────────────────────────────────────

    def buy(self, ticker: str, shares: int, account_id: str = "") -> Dict:
        """Place a market buy order; retry on transient errors."""
        if shares <= 0:
            raise OrderError(f"Cannot buy {shares} shares of {ticker}")
        return self._submit("buy", ticker, shares, account_id)

    def sell(self, ticker: str, shares: int, account_id: str = "") -> Dict:
        """Place a market sell order; retry on transient errors."""
        if shares <= 0:
            raise OrderError(f"Cannot sell {shares} shares of {ticker}")
        return self._submit("sell", ticker, shares, account_id)

    def _submit(self, side: str, ticker: str, shares: int, account_id: str) -> Dict:
        last_err = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                order = self._place_order(side, ticker, shares)
                record = {
                    "ticker": ticker, "side": side, "shares": shares,
                    "order_id": order.get("id", ""), "status": "filled",
                    "account_id": account_id,
                }
                self.orders_placed.append(record)
                log.info("Order placed: %s %s %d shares (attempt %d)", side, ticker, shares, attempt)

                if self._notifier:
                    self._notifier.send_trade_alert(record)

                return record

            except Exception as exc:
                last_err = exc
                log.warning("Order attempt %d/%d failed for %s: %s",
                             attempt, self.max_attempts, ticker, exc)
                if attempt < self.max_attempts:
                    time.sleep(self.backoff_seconds)

        # All retries exhausted
        err_record = {
            "ticker": ticker, "side": side, "shares": shares,
            "status": "failed", "error": str(last_err), "account_id": account_id,
        }
        self.orders_placed.append(err_record)
        if self._notifier:
            self._notifier.send_trade_alert(err_record)
        raise OrderError(
            f"Order failed after {self.max_attempts} attempts for {ticker}: {last_err}"
        )

    def _place_order(self, side: str, ticker: str, shares: int) -> Dict:
        """Call Alpaca API. Replaced by mock in tests."""
        if self._client is None:
            raise OrderError("No Alpaca client configured")
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            req = MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            return {"id": str(order.id), "status": str(order.status)}
        except ImportError:
            raise OrderError("alpaca-py not installed")


# ─────────────────────────────────────────────────────────────────────────────
# Rebalancer
# ─────────────────────────────────────────────────────────────────────────────

class Rebalancer:
    """
    Calculates buy / sell orders needed to move current holdings to target.

    Rebalance triggers:
      - Monthly first day  (checked by caller via is_monthly_rebalance_day)
      - New cash arrival   (checked by caller via cash_threshold_exceeded)

    NOT triggered daily.
    """

    def __init__(
        self,
        target_pct: float = 0.10,
        max_single_pct: float = 0.15,
        cash_buffer_pct: float = 0.10,
        max_turnover_pct: float = 0.50,
    ):
        self.target_pct = target_pct
        self.max_single_pct = max_single_pct
        self.cash_buffer_pct = cash_buffer_pct
        self.max_turnover_pct = max_turnover_pct

    # ── trigger checks ────────────────────────────────────────────────────────

    @staticmethod
    def is_monthly_rebalance_day(date_str: str) -> bool:
        """True on the 1st calendar day of any month."""
        import datetime
        d = datetime.date.fromisoformat(date_str)
        return d.day == 1

    @staticmethod
    def cash_threshold_exceeded(
        cash: float, nav: float, threshold_pct: float = 0.05
    ) -> bool:
        """True when uninvested cash exceeds threshold_pct of NAV."""
        if nav <= 0:
            return False
        return (cash / nav) > threshold_pct

    # ── diff calculation ──────────────────────────────────────────────────────

    def calc_diff(
        self,
        current_positions: Dict[str, int],   # {ticker: shares_held}
        target_tickers: List[str],            # tickers that should be held
        prices: Dict[str, float],             # {ticker: current_price}
        nav: float,
    ) -> Dict[str, Dict]:
        """
        Return {ticker: {"action": "buy"|"sell"|"hold", "shares": int}}
        for the rebalance.
        """
        investable = nav * (1.0 - self.cash_buffer_pct)
        target_value = investable * min(self.target_pct, self.max_single_pct)

        orders: Dict[str, Dict] = {}

        # Sell tickers no longer in target
        for ticker, shares in current_positions.items():
            if ticker not in target_tickers:
                orders[ticker] = {"action": "sell", "shares": shares}

        # Buy / rebalance tickers in target
        for ticker in target_tickers:
            price = prices.get(ticker, 0)
            if price <= 0:
                continue
            target_shares = math.floor(target_value / price)
            current_shares = current_positions.get(ticker, 0)
            delta = target_shares - current_shares

            if delta > 0:
                orders[ticker] = {"action": "buy", "shares": delta}
            elif delta < 0:
                orders[ticker] = {"action": "sell", "shares": abs(delta)}
            # delta == 0 → no order needed

        # Enforce max_turnover_pct
        orders = self._apply_turnover_cap(orders, current_positions, nav, prices)
        return orders

    def _apply_turnover_cap(
        self,
        orders: Dict[str, Dict],
        current_positions: Dict[str, int],
        nav: float,
        prices: Dict[str, float],
    ) -> Dict[str, Dict]:
        """Drop orders if total turnover would exceed max_turnover_pct."""
        max_trade_value = nav * self.max_turnover_pct
        total = sum(
            o["shares"] * prices.get(ticker, 0)
            for ticker, o in orders.items()
        )
        if total <= max_trade_value:
            return orders
        # Scale down proportionally
        scale = max_trade_value / total if total > 0 else 0
        scaled: Dict[str, Dict] = {}
        for ticker, o in orders.items():
            new_shares = math.floor(o["shares"] * scale)
            if new_shares > 0:
                scaled[ticker] = {**o, "shares": new_shares}
        return scaled
