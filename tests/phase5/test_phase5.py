"""
Phase 5 Test Suite — 8 test cases (TC-5-01 through TC-5-08)

Run: pytest tests/phase5/ -v
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from report_generator import ReportModel, ReportView

# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _positions():
    return [
        {
            "ticker": "AAPL",
            "shares": 20,
            "price": 180.0,
            "pe_ratio": 28.5,
            "prev_close_1d": 175.0,
            "prev_close_1w": 170.0,
            "prev_close_1m": 160.0,
        },
        {
            "ticker": "MSFT",
            "shares": 10,
            "price": 400.0,
            "pe_ratio": 35.0,
            "prev_close_1d": 398.0,
            "prev_close_1w": 390.0,
            "prev_close_1m": 380.0,
        },
    ]


def _trades():
    return [
        {"ticker": "NVDA", "side": "buy",  "shares": 5, "price": 500.0, "status": "filled"},
        {"ticker": "AAPL", "side": "sell", "shares": 3, "price": 180.0, "status": "filled"},
    ]


def _top10():
    return [
        {"ticker": "NVDA", "rank": 1, "score": 91.5, "pe_ratio": 55.0, "momentum_90d": 0.42},
        {"ticker": "AAPL", "rank": 2, "score": 88.2, "pe_ratio": 28.5, "momentum_90d": 0.18},
    ]


def _nav_history():
    return [
        {"date": "2025-05-01", "nav": 95_000},
        {"date": "2025-05-15", "nav": 98_000},
        {"date": "2025-05-30", "nav": 105_000},  # peak
    ]


def _benchmark():
    return {"spy_1d": 0.0052, "qqq_1d": 0.0078, "nav_1d": 0.0031}


def _watchlist():
    return {
        "AI & Chips": ["NVDA", "AMD", "INTC"],
        "Cloud": ["MSFT", "AMZN", "GOOGL"],
        "Momentum Leaders": ["AAPL", "META"],
    }


def _build_report(tmp_dir, nav=103_000, cash=7_000):
    model = ReportModel(reports_dir=str(tmp_dir))
    return model.build(
        account_id="acc_001",
        report_date="2025-06-01",
        nav=nav,
        cash=cash,
        positions=_positions(),
        trades=_trades(),
        top10=_top10(),
        watchlist=_watchlist(),
        benchmark=_benchmark(),
        nav_history=_nav_history(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-01  報告 JSON 結構驗證
# ─────────────────────────────────────────────────────────────────────────────

class TestTC501ReportJsonStructure:

    def test_required_top_level_keys(self, tmp_path):
        report = _build_report(tmp_path)
        required = {
            "date", "account_id", "nav", "cash", "invested_value",
            "positions", "trades", "drawdown_pct", "top10", "watchlist",
            "benchmark", "nav_history", "risk_disclaimer", "generated_at",
        }
        assert required.issubset(report.keys())

    def test_nav_and_cash_values(self, tmp_path):
        report = _build_report(tmp_path, nav=103_000, cash=7_000)
        assert report["nav"] == pytest.approx(103_000)
        assert report["cash"] == pytest.approx(7_000)

    def test_invested_value_is_sum_of_positions(self, tmp_path):
        report = _build_report(tmp_path)
        # 20*180 + 10*400 = 3600 + 4000 = 7600
        assert report["invested_value"] == pytest.approx(7_600)

    def test_risk_disclaimer_present(self, tmp_path):
        report = _build_report(tmp_path)
        assert "風險提示" in report["risk_disclaimer"]
        assert "不構成投資建議" in report["risk_disclaimer"]

    def test_generated_at_is_iso_format(self, tmp_path):
        report = _build_report(tmp_path)
        ts = report["generated_at"]
        assert ts.endswith("Z")
        # basic ISO check: YYYY-MM-DDTHH:MM:SS
        assert "T" in ts


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-02  1d/1w/1m 持倉回報計算
# ─────────────────────────────────────────────────────────────────────────────

class TestTC502PositionReturns:

    def _aapl(self, tmp_path):
        report = _build_report(tmp_path)
        return next(p for p in report["positions"] if p["ticker"] == "AAPL")

    def test_return_1d_calculated(self, tmp_path):
        aapl = self._aapl(tmp_path)
        # (180 - 175) / 175 = 0.02857
        assert aapl["return_1d"] == pytest.approx(5 / 175, rel=1e-4)

    def test_return_1w_calculated(self, tmp_path):
        aapl = self._aapl(tmp_path)
        assert aapl["return_1w"] == pytest.approx(10 / 170, rel=1e-4)

    def test_return_1m_calculated(self, tmp_path):
        aapl = self._aapl(tmp_path)
        assert aapl["return_1m"] == pytest.approx(20 / 160, rel=1e-4)

    def test_missing_prev_close_returns_none(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        pos_no_prev = [{"ticker": "XYZ", "shares": 5, "price": 100.0}]
        report = model.build(
            account_id="acc_001", report_date="2025-06-01",
            nav=500, cash=0, positions=pos_no_prev,
            trades=[], top10=[], watchlist={}, benchmark={}, nav_history=[],
        )
        xyz = report["positions"][0]
        assert xyz["return_1d"] is None
        assert xyz["return_1w"] is None
        assert xyz["return_1m"] is None

    def test_pct_of_nav_calculated(self, tmp_path):
        report = _build_report(tmp_path, nav=100_000)
        aapl = next(p for p in report["positions"] if p["ticker"] == "AAPL")
        # 20*180 = 3600 / 100000 = 0.036
        assert aapl["pct_of_nav"] == pytest.approx(3_600 / 100_000, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-03  回撤計算
# ─────────────────────────────────────────────────────────────────────────────

class TestTC503DrawdownCalculation:

    def test_drawdown_from_peak_nav_history(self, tmp_path):
        # Peak in nav_history = 105_000; current NAV = 103_000
        # drawdown = (105k - 103k) / 105k ≈ 0.01905
        report = _build_report(tmp_path, nav=103_000)
        assert report["drawdown_pct"] == pytest.approx(2_000 / 105_000, rel=1e-4)

    def test_zero_drawdown_when_at_peak(self, tmp_path):
        report = _build_report(tmp_path, nav=105_000)
        assert report["drawdown_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_drawdown_when_new_peak(self, tmp_path):
        # current NAV (110k) above all history → drawdown = 0
        report = _build_report(tmp_path, nav=110_000)
        assert report["drawdown_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_empty_nav_history_drawdown_zero(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        report = model.build(
            account_id="acc_001", report_date="2025-06-01",
            nav=100_000, cash=5_000, positions=[], trades=[],
            top10=[], watchlist={}, benchmark={}, nav_history=[],
        )
        assert report["drawdown_pct"] == pytest.approx(0.0, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-04  報告儲存與讀取
# ─────────────────────────────────────────────────────────────────────────────

class TestTC504ReportPersistence:

    def test_save_creates_file_at_correct_path(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        report = _build_report(tmp_path)
        path = model.save(report)
        expected = tmp_path / "2025-06-01" / "acc_001.json"
        assert path == expected
        assert expected.exists()

    def test_saved_file_is_valid_json(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        report = _build_report(tmp_path)
        path = model.save(report)
        loaded = json.loads(path.read_text())
        assert loaded["account_id"] == "acc_001"

    def test_load_returns_saved_report(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        report = _build_report(tmp_path)
        model.save(report)
        loaded = model.load("acc_001", "2025-06-01")
        assert loaded is not None
        assert loaded["nav"] == pytest.approx(103_000)

    def test_load_returns_none_for_missing_report(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        result = model.load("acc_001", "2025-01-01")
        assert result is None

    def test_list_dates_returns_sorted_dates(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        for date in ["2025-06-03", "2025-06-01", "2025-06-02"]:
            r = model.build(
                account_id="acc_001", report_date=date,
                nav=100_000, cash=5_000, positions=[], trades=[],
                top10=[], watchlist={}, benchmark={}, nav_history=[],
            )
            model.save(r)
        dates = model.list_dates("acc_001")
        assert dates == ["2025-06-01", "2025-06-02", "2025-06-03"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-05  HTML 渲染
# ─────────────────────────────────────────────────────────────────────────────

class TestTC505HtmlRendering:

    def test_render_returns_html_string(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        html = view.render(report)
        assert isinstance(html, str)
        assert len(html) > 100

    def test_html_contains_account_id(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        html = view.render(report)
        assert "acc_001" in html

    def test_html_contains_nav(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        html = view.render(report)
        assert "103" in html  # NAV 103,000 somewhere

    def test_html_contains_risk_disclaimer(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        html = view.render(report)
        assert "風險提示" in html

    def test_plain_fallback_when_no_template(self, tmp_path):
        """ReportView falls back gracefully when template directory is missing."""
        report = _build_report(tmp_path)
        view = ReportView(template_dir="/nonexistent/dir")
        html = view.render(report)
        assert "acc_001" in html
        assert "風險提示" in html


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-06  Email 內文生成
# ─────────────────────────────────────────────────────────────────────────────

class TestTC506EmailBodyGeneration:

    def test_plain_body_contains_nav(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        plain, _ = view.render_email_body(report)
        assert "103" in plain  # NAV

    def test_plain_body_contains_risk_disclaimer(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        plain, _ = view.render_email_body(report)
        assert "風險提示" in plain

    def test_plain_body_contains_top10_tickers(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        plain, _ = view.render_email_body(report)
        assert "NVDA" in plain
        assert "AAPL" in plain

    def test_plain_body_contains_drawdown(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        plain, _ = view.render_email_body(report)
        assert "Drawdown" in plain

    def test_html_body_is_non_empty_string(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        _, html = view.render_email_body(report)
        assert isinstance(html, str)
        assert "<" in html  # some HTML tags present


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-07  Watchlist 三類別顯示
# ─────────────────────────────────────────────────────────────────────────────

class TestTC507WatchlistCategories:

    def test_three_categories_in_report(self, tmp_path):
        report = _build_report(tmp_path)
        assert len(report["watchlist"]) == 3

    def test_category_names_preserved(self, tmp_path):
        report = _build_report(tmp_path)
        assert "AI & Chips" in report["watchlist"]
        assert "Cloud" in report["watchlist"]
        assert "Momentum Leaders" in report["watchlist"]

    def test_category_tickers_preserved(self, tmp_path):
        report = _build_report(tmp_path)
        assert "NVDA" in report["watchlist"]["AI & Chips"]
        assert "MSFT" in report["watchlist"]["Cloud"]

    def test_html_contains_all_categories(self, tmp_path):
        report = _build_report(tmp_path)
        view = ReportView(template_dir="dashboard/templates")
        html = view.render(report)
        assert "AI &amp; Chips" in html or "AI & Chips" in html
        assert "Cloud" in html
        assert "Momentum Leaders" in html


# ─────────────────────────────────────────────────────────────────────────────
# TC-5-08  歷史報告查詢
# ─────────────────────────────────────────────────────────────────────────────

class TestTC508HistoricalReportRetrieval:

    def test_load_specific_date(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        for nav, date in [(100_000, "2025-06-01"), (102_000, "2025-06-02")]:
            r = model.build(
                account_id="acc_001", report_date=date,
                nav=nav, cash=5_000, positions=[], trades=[],
                top10=[], watchlist={}, benchmark={}, nav_history=[],
            )
            model.save(r)
        report = model.load("acc_001", "2025-06-02")
        assert report["nav"] == pytest.approx(102_000)

    def test_different_accounts_isolated(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        for acct, nav in [("acc_001", 100_000), ("acc_002", 50_000)]:
            r = model.build(
                account_id=acct, report_date="2025-06-01",
                nav=nav, cash=5_000, positions=[], trades=[],
                top10=[], watchlist={}, benchmark={}, nav_history=[],
            )
            model.save(r)
        r1 = model.load("acc_001", "2025-06-01")
        r2 = model.load("acc_002", "2025-06-01")
        assert r1["nav"] == pytest.approx(100_000)
        assert r2["nav"] == pytest.approx(50_000)

    def test_list_dates_only_for_account(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        # Save for acc_001 on two dates
        for date in ["2025-06-01", "2025-06-02"]:
            r = model.build(
                account_id="acc_001", report_date=date,
                nav=100_000, cash=5_000, positions=[], trades=[],
                top10=[], watchlist={}, benchmark={}, nav_history=[],
            )
            model.save(r)
        # Save for acc_002 on one date
        r = model.build(
            account_id="acc_002", report_date="2025-06-01",
            nav=50_000, cash=3_000, positions=[], trades=[],
            top10=[], watchlist={}, benchmark={}, nav_history=[],
        )
        model.save(r)
        assert model.list_dates("acc_001") == ["2025-06-01", "2025-06-02"]
        assert model.list_dates("acc_002") == ["2025-06-01"]

    def test_load_nonexistent_date_returns_none(self, tmp_path):
        model = ReportModel(reports_dir=str(tmp_path))
        assert model.load("acc_001", "2099-01-01") is None

    def test_reports_json_contains_unicode(self, tmp_path):
        """Chinese characters survive JSON round-trip."""
        model = ReportModel(reports_dir=str(tmp_path))
        report = _build_report(tmp_path)
        path = model.save(report)
        raw = path.read_text(encoding="utf-8")
        assert "風險提示" in raw
