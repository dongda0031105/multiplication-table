"""
Phase 7 Test Suite — 6 test cases (TC-7-01 through TC-7-06)

Run: pytest tests/phase7/ -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from e2e_runner import E2ERunner, GoLiveChecklist, PipelineError
from notifier import Notifier
from report_generator import ReportModel, ReportView

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_account(account_id="acc_001", strategy_id="strat_v1"):
    return {
        "id": account_id,
        "active_strategy_id": strategy_id,
        "notify_email": "test@example.com",
        "watchlist_categories": {
            "AI": ["NVDA", "AMD"],
            "Cloud": ["MSFT"],
            "Momentum": ["AAPL"],
        },
    }


def _mock_snapshot(nav=100_000, cash=8_000):
    return {
        "nav": nav,
        "cash": cash,
        "positions": [
            {
                "ticker": "AAPL",
                "shares": 10,
                "price": 180.0,
                "pe_ratio": 28.5,
                "prev_close_1d": 178.0,
                "prev_close_1w": 172.0,
                "prev_close_1m": 160.0,
            }
        ],
        "benchmark": {"spy_1d": 0.003, "qqq_1d": 0.004, "nav_1d": 0.002},
        "nav_history": [{"date": "2025-05-30", "nav": 99_000}],
        "top10": [
            {"ticker": "NVDA", "rank": 1, "score": 91.5,
             "pe_ratio": 55.0, "momentum_90d": 0.42}
        ],
    }


def _make_runner(tmp_path, dry_run=False, fail_config=False):
    """Build an E2ERunner with all mocked components."""
    account_mgr = MagicMock()
    account_mgr.list_accounts.return_value = [_mock_account()]

    strategy_loader = MagicMock()
    strategy_loader.load.return_value = {"id": "strat_v1", "portfolio": {}}

    data_pipeline = MagicMock()
    data_pipeline.fetch_snapshot.return_value = _mock_snapshot()

    indicator_engine = MagicMock()
    indicator_engine.compute_snapshot.side_effect = lambda snap, strat: snap

    derived_factor_engine = MagicMock()

    filter_engine = MagicMock()
    filter_engine.apply_snapshot.side_effect = lambda snap, strat: snap

    ranking_engine = MagicMock()
    snapshot_with_top10 = {**_mock_snapshot(), "top10": _mock_snapshot()["top10"]}
    ranking_engine.rank_snapshot.return_value = snapshot_with_top10

    signal_engine = MagicMock()
    signal_engine.entry_signals_snapshot.return_value = ["NVDA"]
    signal_engine.exit_signals_snapshot.return_value = {}

    exec_engine = MagicMock()
    exec_engine.buy.return_value = {
        "ticker": "NVDA", "side": "buy", "shares": 1,
        "status": "filled", "account_id": "acc_001",
    }

    reports_dir = tmp_path / "reports"
    out_dir = tmp_path / "docs"
    report_model = ReportModel(reports_dir=str(reports_dir))
    report_view = ReportView(template_dir="dashboard/templates")

    from dashboard_builder import DashboardBuilder
    dashboard = DashboardBuilder(str(reports_dir), str(out_dir))

    notifier = MagicMock(spec=Notifier)
    notifier.send_daily_report.return_value = True

    if fail_config:
        account_mgr.list_accounts.return_value = []  # no accounts → config fails

    return E2ERunner(
        account_manager=account_mgr,
        strategy_loader=strategy_loader,
        data_pipeline=data_pipeline,
        indicator_engine=indicator_engine,
        derived_factor_engine=derived_factor_engine,
        filter_engine=filter_engine,
        ranking_engine=ranking_engine,
        signal_engine=signal_engine,
        execution_engine=exec_engine,
        report_model=report_model,
        report_view=report_view,
        dashboard_builder=dashboard,
        notifier=notifier,
        dry_run=dry_run,
    ), notifier


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-01  端對端管道成功運行
# ─────────────────────────────────────────────────────────────────────────────

class TestTC701PipelineSuccess:

    def test_run_returns_success(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        result = runner.run("acc_001", run_date="2025-06-01")
        assert result["success"] is True

    def test_all_steps_completed(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        expected = ["config", "data", "indicators", "filters",
                    "ranking", "signals", "execution", "report",
                    "dashboard", "email"]
        assert runner.steps_completed == expected

    def test_result_contains_account_and_date(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        result = runner.run("acc_001", run_date="2025-06-15")
        assert result["account_id"] == "acc_001"
        assert result["date"] == "2025-06-15"

    def test_result_contains_orders(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        result = runner.run("acc_001", run_date="2025-06-01")
        assert isinstance(result["orders"], list)
        assert any(o["ticker"] == "NVDA" for o in result["orders"])

    def test_report_saved_to_disk(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        report_file = tmp_path / "reports" / "2025-06-01" / "acc_001.json"
        assert report_file.exists()


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-02  Dry-Run 模式
# ─────────────────────────────────────────────────────────────────────────────

class TestTC702DryRunMode:

    def test_dry_run_no_orders_placed(self, tmp_path):
        runner, _ = _make_runner(tmp_path, dry_run=True)
        result = runner.run("acc_001", run_date="2025-06-01")
        assert result["dry_run"] is True
        assert result["orders"] == []

    def test_dry_run_execution_engine_not_called(self, tmp_path):
        runner, _ = _make_runner(tmp_path, dry_run=True)
        runner.run("acc_001", run_date="2025-06-01")
        runner.execution_engine.buy.assert_not_called()
        runner.execution_engine.sell.assert_not_called()

    def test_dry_run_still_saves_report(self, tmp_path):
        runner, _ = _make_runner(tmp_path, dry_run=True)
        runner.run("acc_001", run_date="2025-06-01")
        report_file = tmp_path / "reports" / "2025-06-01" / "acc_001.json"
        assert report_file.exists()

    def test_dry_run_still_sends_email(self, tmp_path):
        runner, notifier = _make_runner(tmp_path, dry_run=True)
        runner.run("acc_001", run_date="2025-06-01")
        notifier.send_daily_report.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-03  管道失敗通知
# ─────────────────────────────────────────────────────────────────────────────

class TestTC703FailureNotification:

    def test_pipeline_error_raises_pipeline_error(self, tmp_path):
        runner, _ = _make_runner(tmp_path, fail_config=True)
        with pytest.raises(PipelineError):
            runner.run("acc_001", run_date="2025-06-01")

    def test_notifier_called_on_failure(self, tmp_path):
        runner, notifier = _make_runner(tmp_path, fail_config=True)
        with pytest.raises(PipelineError):
            runner.run("acc_001", run_date="2025-06-01")
        notifier.send_trade_alert.assert_called_once()
        call_arg = notifier.send_trade_alert.call_args[0][0]
        assert call_arg["status"] == "failed"

    def test_failure_alert_contains_account_id(self, tmp_path):
        runner, notifier = _make_runner(tmp_path, fail_config=True)
        with pytest.raises(PipelineError):
            runner.run("acc_001", run_date="2025-06-01")
        call_arg = notifier.send_trade_alert.call_args[0][0]
        assert call_arg["account_id"] == "acc_001"

    def test_steps_completed_reflects_failure_point(self, tmp_path):
        runner, _ = _make_runner(tmp_path, fail_config=True)
        with pytest.raises(PipelineError):
            runner.run("acc_001", run_date="2025-06-01")
        # config step fails → steps_completed should be empty
        assert "config" not in runner.steps_completed


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-04  Email 通知整合
# ─────────────────────────────────────────────────────────────────────────────

class TestTC704EmailIntegration:

    def test_daily_report_email_sent(self, tmp_path):
        runner, notifier = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        notifier.send_daily_report.assert_called_once()

    def test_email_sent_to_notify_email(self, tmp_path):
        runner, notifier = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        call_args = notifier.send_daily_report.call_args
        to_email = call_args[0][0]
        assert to_email == "test@example.com"

    def test_email_subject_contains_date(self, tmp_path):
        runner, notifier = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        call_args = notifier.send_daily_report.call_args
        subject = call_args[0][1]
        assert "2025-06-01" in subject

    def test_email_body_contains_risk_disclaimer(self, tmp_path):
        runner, notifier = _make_runner(tmp_path)
        runner.run("acc_001", run_date="2025-06-01")
        call_args = notifier.send_daily_report.call_args
        plain_body = call_args[0][3]
        assert "風險提示" in plain_body


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-05  Go-Live 清單
# ─────────────────────────────────────────────────────────────────────────────

class TestTC705GoLiveChecklist:

    def test_all_items_false_by_default(self):
        cl = GoLiveChecklist()
        assert cl.all_passed() is False

    def test_all_passed_when_all_checked(self):
        cl = GoLiveChecklist()
        for item in cl._items:
            cl.check(item, True)
        assert cl.all_passed() is True

    def test_missing_returns_unchecked_items(self):
        cl = GoLiveChecklist()
        cl.check("paper_trading_tested", True)
        missing = cl.missing()
        assert "paper_trading_tested" not in missing
        assert "live_credentials_set" in missing

    def test_unknown_item_raises(self):
        cl = GoLiveChecklist()
        with pytest.raises(ValueError):
            cl.check("nonexistent_item", True)

    def test_status_returns_all_items(self):
        cl = GoLiveChecklist()
        status = cl.status()
        assert len(status) == len(cl._items)
        assert all(v is False for v in status.values())


# ─────────────────────────────────────────────────────────────────────────────
# TC-7-06  CLAUDE.md 存在且包含關鍵章節
# ─────────────────────────────────────────────────────────────────────────────

class TestTC706ClaudeMd:

    def _read_claude_md(self) -> str:
        root = Path(__file__).parent.parent.parent
        claude_md = root / "CLAUDE.md"
        assert claude_md.exists(), "CLAUDE.md not found at project root"
        return claude_md.read_text(encoding="utf-8")

    def test_claude_md_exists(self):
        root = Path(__file__).parent.parent.parent
        assert (root / "CLAUDE.md").exists()

    def test_contains_architecture_section(self):
        text = self._read_claude_md()
        assert "Architecture" in text or "架構" in text

    def test_contains_credential_guidance(self):
        text = self._read_claude_md()
        assert "credentials" in text.lower() or "secret" in text.lower()

    def test_contains_go_live_section(self):
        text = self._read_claude_md()
        assert "go-live" in text.lower() or "GoLive" in text or "go_live" in text.lower()

    def test_contains_risk_disclaimer_reference(self):
        text = self._read_claude_md()
        assert "風險提示" in text or "risk" in text.lower()
