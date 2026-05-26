"""
Phase 4 Test Suite — 8 test cases (TC-4-01 through TC-4-08)

Run: pytest tests/phase4/ -v
"""
import math
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from execution_engine import ExecutionEngine, OrderError, Rebalancer
from notifier import Notifier

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine(fail_attempts: int = 0) -> tuple:
    """
    Return (engine, mock_notifier).
    fail_attempts: number of times _place_order raises before succeeding.
    """
    notifier = MagicMock(spec=Notifier)
    engine = ExecutionEngine(notifier=notifier, max_attempts=3, backoff_seconds=0)

    call_count = [0]

    def mock_place(side, ticker, shares):
        call_count[0] += 1
        if call_count[0] <= fail_attempts:
            raise RuntimeError("Transient API error")
        return {"id": f"order_{call_count[0]}", "status": "filled"}

    engine._place_order = mock_place
    return engine, notifier


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-01  整數股計算
# ─────────────────────────────────────────────────────────────────────────────

class TestTC401WholeShareCalculation:

    def test_floor_division_basic(self):
        # $10,000 / $327.50 = 30.53 → 30
        assert ExecutionEngine.calc_shares(10_000, 327.50) == 30

    def test_exact_integer_result(self):
        assert ExecutionEngine.calc_shares(1_000, 100.0) == 10

    def test_never_returns_fractional(self):
        # Any price that would give fractional result → floored
        for price in [13.33, 99.99, 250.01, 500.0]:
            shares = ExecutionEngine.calc_shares(10_000, price)
            assert shares == math.floor(10_000 / price)
            assert isinstance(shares, int)

    def test_zero_price_returns_zero(self):
        assert ExecutionEngine.calc_shares(10_000, 0) == 0

    def test_target_values_respect_max_single_pct(self):
        # NAV=$100k, target=10%, max_single=15%  → base = $10k per ticker
        targets = ExecutionEngine.calc_target_values(
            nav=100_000, target_pct=0.10, tickers=["AAPL", "MSFT"], max_single_pct=0.15
        )
        for t, val in targets.items():
            assert val <= 100_000 * 0.15
            assert val == pytest.approx(10_000)

    def test_target_capped_at_max_single(self):
        # target_pct=0.20 but max_single=0.15 → capped at 15%
        targets = ExecutionEngine.calc_target_values(
            nav=100_000, target_pct=0.20, tickers=["NVDA"], max_single_pct=0.15
        )
        assert targets["NVDA"] == pytest.approx(15_000)


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-02  10% 持倉上限
# ─────────────────────────────────────────────────────────────────────────────

class TestTC402PositionLimit:

    def test_10pct_of_nav_per_ticker(self):
        nav = 100_000
        targets = ExecutionEngine.calc_target_values(
            nav=nav, target_pct=0.10, tickers=["AAPL"], max_single_pct=0.15
        )
        assert targets["AAPL"] == pytest.approx(nav * 0.10)

    def test_shares_calculated_from_nav_target(self):
        nav = 100_000
        price = 500.0
        target_value = nav * 0.10
        expected_shares = math.floor(target_value / price)  # 20
        assert ExecutionEngine.calc_shares(target_value, price) == expected_shares

    def test_multiple_tickers_each_get_10pct(self):
        nav = 100_000
        tickers = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        targets = ExecutionEngine.calc_target_values(
            nav=nav, target_pct=0.10, tickers=tickers, max_single_pct=0.15
        )
        for t in tickers:
            assert targets[t] == pytest.approx(nav * 0.10)


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-03  Paper Trading 下單 (mocked Alpaca)
# ─────────────────────────────────────────────────────────────────────────────

class TestTC403PaperTradingOrders:

    def test_buy_order_returns_record(self):
        engine, _ = _make_engine()
        record = engine.buy("AAPL", 10, "acc_001")
        assert record["ticker"] == "AAPL"
        assert record["side"] == "buy"
        assert record["shares"] == 10
        assert record["status"] == "filled"

    def test_sell_order_returns_record(self):
        engine, _ = _make_engine()
        record = engine.sell("NVDA", 5, "acc_001")
        assert record["side"] == "sell"
        assert record["shares"] == 5

    def test_order_appended_to_audit_log(self):
        engine, _ = _make_engine()
        engine.buy("AAPL", 10)
        engine.sell("MSFT", 5)
        assert len(engine.orders_placed) == 2

    def test_buy_zero_shares_raises(self):
        engine, _ = _make_engine()
        with pytest.raises(OrderError, match="Cannot buy 0"):
            engine.buy("AAPL", 0)

    def test_sell_zero_shares_raises(self):
        engine, _ = _make_engine()
        with pytest.raises(OrderError, match="Cannot sell 0"):
            engine.sell("AAPL", 0)


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-04  重試機制
# ─────────────────────────────────────────────────────────────────────────────

class TestTC404RetryMechanism:

    def test_succeeds_after_one_failure(self):
        engine, _ = _make_engine(fail_attempts=1)
        record = engine.buy("AAPL", 10)
        assert record["status"] == "filled"

    def test_succeeds_after_two_failures(self):
        engine, _ = _make_engine(fail_attempts=2)
        record = engine.buy("AAPL", 10)
        assert record["status"] == "filled"

    def test_raises_after_max_attempts(self):
        engine, notifier = _make_engine(fail_attempts=10)  # always fail
        with pytest.raises(OrderError):
            engine.buy("AAPL", 10)

    def test_failure_record_appended_to_audit_log(self):
        engine, _ = _make_engine(fail_attempts=10)
        with pytest.raises(OrderError):
            engine.buy("AAPL", 10)
        assert engine.orders_placed[-1]["status"] == "failed"

    def test_notifier_called_on_failure(self):
        engine, notifier = _make_engine(fail_attempts=10)
        with pytest.raises(OrderError):
            engine.buy("AAPL", 10)
        notifier.send_trade_alert.assert_called_once()
        call_arg = notifier.send_trade_alert.call_args[0][0]
        assert call_arg["status"] == "failed"


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-05  月初再平衡觸發
# ─────────────────────────────────────────────────────────────────────────────

class TestTC405MonthlyRebalanceTrigger:

    def test_triggers_on_first_of_month(self):
        assert Rebalancer.is_monthly_rebalance_day("2025-06-01") is True
        assert Rebalancer.is_monthly_rebalance_day("2025-01-01") is True
        assert Rebalancer.is_monthly_rebalance_day("2025-12-01") is True

    def test_does_not_trigger_on_other_days(self):
        for day in ["2025-06-02", "2025-06-15", "2025-06-30"]:
            assert Rebalancer.is_monthly_rebalance_day(day) is False

    def test_calc_diff_sells_removed_tickers(self):
        reb = Rebalancer(target_pct=0.10)
        # AAPL held but no longer in target
        result = reb.calc_diff(
            current_positions={"AAPL": 10, "MSFT": 5},
            target_tickers=["MSFT"],
            prices={"AAPL": 150.0, "MSFT": 400.0},
            nav=100_000,
        )
        assert "AAPL" in result
        assert result["AAPL"]["action"] == "sell"
        assert result["AAPL"]["shares"] == 10

    def test_calc_diff_buys_new_tickers(self):
        reb = Rebalancer(target_pct=0.10)
        result = reb.calc_diff(
            current_positions={},
            target_tickers=["NVDA"],
            prices={"NVDA": 500.0},
            nav=100_000,
        )
        assert "NVDA" in result
        assert result["NVDA"]["action"] == "buy"
        # 10% of $100k = $10k / $500 = 20 shares
        # (minus cash_buffer: investable=$90k → target $9k / $500 = 18)
        assert result["NVDA"]["shares"] == 18

    def test_no_order_when_already_at_target(self):
        reb = Rebalancer(target_pct=0.10, cash_buffer_pct=0.0)
        # NAV=$100k, target 10% = $10k, price=$100 → 100 shares
        result = reb.calc_diff(
            current_positions={"AAPL": 100},
            target_tickers=["AAPL"],
            prices={"AAPL": 100.0},
            nav=100_000,
        )
        # delta = 100 - 100 = 0 → no order
        assert "AAPL" not in result


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-06  新資金再平衡觸發
# ─────────────────────────────────────────────────────────────────────────────

class TestTC406NewCashRebalanceTrigger:

    def test_triggers_when_cash_exceeds_threshold(self):
        # NAV=$100k, cash=$16k → 16% > 5% threshold
        assert Rebalancer.cash_threshold_exceeded(16_000, 100_000, 0.05) is True

    def test_no_trigger_when_cash_below_threshold(self):
        assert Rebalancer.cash_threshold_exceeded(4_000, 100_000, 0.05) is False

    def test_exact_threshold_not_triggered(self):
        # 5% exactly is not exceeded
        assert Rebalancer.cash_threshold_exceeded(5_000, 100_000, 0.05) is False

    def test_zero_nav_safe(self):
        assert Rebalancer.cash_threshold_exceeded(1_000, 0, 0.05) is False


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-07  即時交易 Email 通知
# ─────────────────────────────────────────────────────────────────────────────

class TestTC407TradeEmailNotification:

    def test_notifier_called_on_successful_buy(self):
        engine, notifier = _make_engine()
        engine.buy("AAPL", 10, "acc_001")
        notifier.send_trade_alert.assert_called_once()
        order_arg = notifier.send_trade_alert.call_args[0][0]
        assert order_arg["ticker"] == "AAPL"
        assert order_arg["side"] == "buy"

    def test_notifier_called_on_successful_sell(self):
        engine, notifier = _make_engine()
        engine.sell("MSFT", 5, "acc_001")
        notifier.send_trade_alert.assert_called_once()

    def test_notifier_email_includes_account_id(self):
        engine, notifier = _make_engine()
        engine.buy("NVDA", 20, "acc_002")
        order_arg = notifier.send_trade_alert.call_args[0][0]
        assert order_arg["account_id"] == "acc_002"

    def test_notifier_no_credentials_logs_warning(self):
        """Notifier gracefully skips send when credentials are missing."""
        n = Notifier(smtp_user="", smtp_pass="")
        result = n.send_trade_alert({"ticker": "AAPL", "side": "buy", "shares": 10, "status": "filled"})
        assert result is False
        assert n.last_sent()["sent"] is False
        assert n.last_sent()["reason"] == "no_credentials"

    def test_trade_alert_body_contains_risk_disclaimer(self):
        """send_trade_alert should include the risk disclaimer text."""
        import email as email_lib
        n = Notifier(smtp_user="test@test.com", smtp_pass="pass")
        with patch("notifier.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__ = lambda s: mock_smtp.return_value
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            mock_smtp.return_value.sendmail = MagicMock()
            n.send_trade_alert({"ticker": "AAPL", "side": "buy", "shares": 10, "status": "filled"})

        raw_email = mock_smtp.return_value.sendmail.call_args[0][2]
        # Parse MIME and decode base64 body
        msg = email_lib.message_from_string(raw_email)
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                body = payload.decode("utf-8")
        assert "不構成投資建議" in body or "風險提示" in body


# ─────────────────────────────────────────────────────────────────────────────
# TC-4-08  多帳戶並行安全
# ─────────────────────────────────────────────────────────────────────────────

class TestTC408MultiAccountSafety:

    def test_orders_tagged_with_account_id(self):
        engine, _ = _make_engine()
        engine.buy("AAPL", 10, "acc_001")
        engine.buy("NVDA", 5, "acc_002")
        ids = [o["account_id"] for o in engine.orders_placed]
        assert "acc_001" in ids
        assert "acc_002" in ids

    def test_separate_engines_do_not_share_audit_logs(self):
        e1, _ = _make_engine()
        e2, _ = _make_engine()
        e1.buy("AAPL", 10, "acc_001")
        assert len(e1.orders_placed) == 1
        assert len(e2.orders_placed) == 0  # independent

    def test_rebalancer_handles_multiple_accounts_independently(self):
        reb1 = Rebalancer(target_pct=0.10)
        reb2 = Rebalancer(target_pct=0.10)

        diff1 = reb1.calc_diff({}, ["AAPL"], {"AAPL": 150.0}, 100_000)
        diff2 = reb2.calc_diff({}, ["NVDA"], {"NVDA": 500.0}, 50_000)

        assert "AAPL" in diff1
        assert "NVDA" in diff2
        assert "NVDA" not in diff1
        assert "AAPL" not in diff2
