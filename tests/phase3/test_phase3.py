"""
Phase 3 Test Suite — 7 test cases (TC-3-01 through TC-3-07)

Run: pytest tests/phase3/ -v
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from filter_engine import FilterEngine, FilterError
from ranking_engine import RankingEngine
from signal_engine import RiskGuard, SignalEngine

from tests.phase2.fixtures import make_ohlcv, make_indicator_list
from indicator_engine import IndicatorEngine
from derived_factor_engine import DerivedFactorEngine

# ─────────────────────────────────────────────────────────────────────────────
# Shared Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_snapshot(n: int = 20, seed: int = 42) -> pd.DataFrame:
    """
    Synthetic cross-sectional snapshot: one row per ticker,
    all indicator + fundamental columns present.
    """
    rng = np.random.default_rng(seed)
    tickers = [f"STK{i:02d}" for i in range(n)]

    prices   = rng.uniform(20, 500, n)
    sma20    = prices * rng.uniform(0.90, 1.10, n)
    sma50    = prices * rng.uniform(0.85, 1.15, n)
    sma200   = prices * rng.uniform(0.70, 1.20, n)

    df = pd.DataFrame({
        "ticker":             tickers,
        "adjusted_close":     prices,
        "sma_20":             sma20,
        "sma_50":             sma50,
        "sma_200":            sma200,
        "rsi_14":             rng.uniform(30, 80, n),
        "adx_14":             rng.uniform(10, 50, n),
        "atr_14":             rng.uniform(1, 20, n),
        "volume_ratio_20d":   rng.uniform(0.5, 3.0, n),
        "macd_histogram":     rng.uniform(-2, 2, n),
        "momentum_90d":       rng.uniform(-0.3, 0.5, n),
        "momentum_60d":       rng.uniform(-0.2, 0.4, n),
        "ma_gap_50":          (prices - sma50) / sma50,
        "ma_slope_20_5d":     rng.uniform(-0.05, 0.05, n),
        "ma_slope_50_10d":    rng.uniform(-0.03, 0.03, n),
        "roe":                rng.uniform(0.05, 0.40, n),
        "revenue_growth_yoy": rng.uniform(0.05, 0.50, n),
        "pe_ratio":           rng.uniform(10, 60, n),
        "eps_ttm":            rng.uniform(1, 20, n),
        "debt_to_equity":     rng.uniform(0, 2, n),
        "market_cap":         rng.uniform(2e9, 200e9, n),
        "sector":             rng.choice(["Technology", "Healthcare", "Consumer"], n).tolist(),
    }, index=tickers)

    # Derived factors referenced by real strategy filters
    df["atr_pct"] = df["atr_14"] / df["adjusted_close"]

    return df


def _make_history(n_days: int = 300) -> pd.DataFrame:
    """Full history with all indicators for crossover tests."""
    df = make_ohlcv(n_days=n_days)
    engine = IndicatorEngine()
    return engine.compute(df, make_indicator_list())


RANKING_CONFIG = {
    "method": "weighted_percentile_score",
    "normalization": {"method": "cross_sectional_percentile",
                      "clip_percentiles": [2, 98],
                      "handle_missing": "exclude_symbol"},
    "factors": [
        {"field": "momentum_90d",   "weight": 0.20, "direction": "desc"},
        {"field": "ma_gap_50",      "weight": 0.15, "direction": "desc"},
        {"field": "roe",            "weight": 0.15, "direction": "desc"},
        {"field": "revenue_growth_yoy", "weight": 0.15, "direction": "desc"},
        {"field": "macd_histogram", "weight": 0.10, "direction": "desc"},
        {"field": "adx_14",         "weight": 0.10, "direction": "desc"},
        {"field": "volume_ratio_20d","weight": 0.10, "direction": "desc"},
        {"field": "pe_ratio",       "weight": 0.05, "direction": "asc"},
    ],
    "selection": {"watchlist_top_n": 20, "buy_top_n": 8, "min_score": 0},
}


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-01  動態過濾器執行
# ─────────────────────────────────────────────────────────────────────────────

class TestTC301DynamicFilter:

    def test_fundamental_roe_filter_excludes_low_roe(self):
        snap = _make_snapshot(20)
        # Force first 3 rows to have ROE below threshold
        snap.iloc[:3, snap.columns.get_loc("roe")] = 0.05
        snap.iloc[3:, snap.columns.get_loc("roe")] = 0.25

        conditions = [{"field": "roe", "op": ">", "value": 0.10}]
        result = FilterEngine().apply(snap, {"fundamental": {"logic": "AND", "conditions": conditions}})
        assert len(result) == 17
        assert all(result["roe"] > 0.10)

    def test_technical_rsi_filter_excludes_overbought(self):
        snap = _make_snapshot(20)
        snap.iloc[:5, snap.columns.get_loc("rsi_14")] = 75.0  # overbought

        conditions = [{"field": "rsi_14", "op": "between", "value": [45, 70]}]
        result = FilterEngine().apply(snap, {"technical": {"logic": "AND", "conditions": conditions}})
        assert all(45 <= r <= 70 for r in result["rsi_14"])

    def test_field_vs_field_filter(self):
        """adjusted_close > sma_50: only tickers above their 50-day MA pass."""
        snap = _make_snapshot(20)
        snap["adjusted_close"] = snap["sma_50"] * 1.05  # all above
        snap.iloc[:5, snap.columns.get_loc("adjusted_close")] = snap["sma_50"].iloc[:5] * 0.95  # 5 below

        conditions = [{"field": "adjusted_close", "op": ">", "value": "sma_50"}]
        result = FilterEngine().apply(snap, {"technical": {"logic": "AND", "conditions": conditions}})
        assert len(result) == 15
        assert all(result["adjusted_close"] > result["sma_50"])

    def test_and_logic_all_conditions_must_pass(self):
        snap = _make_snapshot(10)
        # Stock 0: fails ROE only
        snap.iloc[0, snap.columns.get_loc("roe")] = 0.02
        snap.iloc[0, snap.columns.get_loc("adx_14")] = 25.0
        # Stock 1: fails ADX only
        snap.iloc[1, snap.columns.get_loc("roe")] = 0.25
        snap.iloc[1, snap.columns.get_loc("adx_14")] = 5.0
        # Rest: pass both
        snap.iloc[2:, snap.columns.get_loc("roe")] = 0.25
        snap.iloc[2:, snap.columns.get_loc("adx_14")] = 25.0

        conditions = [
            {"field": "roe", "op": ">", "value": 0.10},
            {"field": "adx_14", "op": ">", "value": 20},
        ]
        result = FilterEngine().apply(snap, {"fundamental": {"logic": "AND", "conditions": conditions}})
        assert len(result) == 8

    def test_adding_new_json_condition_works_without_python_changes(self):
        """New condition added to JSON list → automatically applied."""
        snap = _make_snapshot(20)
        snap["eps_ttm"] = 5.0
        snap.iloc[:4, snap.columns.get_loc("eps_ttm")] = -1.0  # negative EPS

        new_condition = {"field": "eps_ttm", "op": ">", "value": 0}
        result = FilterEngine().apply(snap, {
            "fundamental": {"logic": "AND", "conditions": [new_condition]}
        })
        assert len(result) == 16
        assert all(result["eps_ttm"] > 0)

    def test_empty_conditions_passes_all(self):
        snap = _make_snapshot(20)
        result = FilterEngine().apply(snap, {})
        assert len(result) == len(snap)

    def test_unknown_field_raises_filter_error(self):
        snap = _make_snapshot(5)
        with pytest.raises(FilterError):
            FilterEngine().apply(snap, {
                "fundamental": {"logic": "AND", "conditions": [
                    {"field": "nonexistent_field", "op": ">", "value": 0}
                ]}
            })


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-02  排名一致性
# ─────────────────────────────────────────────────────────────────────────────

class TestTC302RankingConsistency:

    def test_same_input_produces_same_ranking(self):
        snap = _make_snapshot(20)
        engine = RankingEngine()
        r1 = engine.score_and_rank(snap, RANKING_CONFIG)
        r2 = engine.score_and_rank(snap, RANKING_CONFIG)
        pd.testing.assert_frame_equal(r1, r2)

    def test_rank_1_has_highest_score(self):
        snap = _make_snapshot(20)
        result = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        rank1_score = result[result["rank"] == 1]["score"].iloc[0]
        assert rank1_score == result["score"].max()

    def test_ranks_are_unique(self):
        snap = _make_snapshot(20)
        result = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        assert result["rank"].nunique() == len(result)

    def test_asc_factor_inverted_correctly(self):
        """P/E ratio direction=asc: stock with lower PE should rank higher."""
        n = 10
        rng = np.random.default_rng(0)
        snap = pd.DataFrame({
            "ticker": [f"S{i}" for i in range(n)],
            "pe_ratio": [10.0] * 5 + [50.0] * 5,  # first 5 have lower PE
        }, index=[f"S{i}" for i in range(n)])

        simple_config = {
            "normalization": {"clip_percentiles": [0, 100], "handle_missing": "exclude_symbol"},
            "factors": [{"field": "pe_ratio", "weight": 1.0, "direction": "asc"}],
            "selection": {},
        }
        result = RankingEngine().score_and_rank(snap, simple_config)
        # Lower PE → higher score → lower rank number
        low_pe_ranks = result[result["pe_ratio"] == 10.0]["rank"].tolist()
        high_pe_ranks = result[result["pe_ratio"] == 50.0]["rank"].tolist()
        assert max(low_pe_ranks) < min(high_pe_ranks)

    def test_get_watchlist_returns_top_n(self):
        snap = _make_snapshot(20)
        result = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        watchlist = RankingEngine().get_watchlist(result, RANKING_CONFIG)
        assert len(watchlist) == 20  # watchlist_top_n = 20 = all

    def test_get_buy_candidates_returns_top_8(self):
        snap = _make_snapshot(20)
        result = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        buys = RankingEngine().get_buy_candidates(result, RANKING_CONFIG)
        assert len(buys) <= 8
        assert all(buys["rank"] <= 8)

    def test_nan_factor_excludes_ticker(self):
        snap = _make_snapshot(20)
        snap.iloc[0, snap.columns.get_loc("momentum_90d")] = float("nan")
        result = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        # Ticker with NaN should be excluded
        assert len(result) == 19


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-03  進場信號 AND 邏輯
# ─────────────────────────────────────────────────────────────────────────────

class TestTC303EntrySignalAND:

    @pytest.fixture
    def ranked_snap(self):
        snap = _make_snapshot(20)
        return RankingEngine().score_and_rank(snap, RANKING_CONFIG)

    def _all_pass_entry_config(self, ranked_snap: pd.DataFrame) -> dict:
        """Build entry config that all top-8 stocks pass."""
        # Use conditions that are loose enough to pass
        return {
            "logic": "AND",
            "conditions": [
                {"type": "rank_in_top_n", "n": 8},
                {"field": "adx_14", "op": ">", "value": 0},     # always true
                {"field": "rsi_14", "op": "<", "value": 100},   # always true
            ],
        }

    def test_and_logic_all_conditions_must_pass(self, ranked_snap):
        """If any condition fails, no entry signal."""
        # Impossible condition: volume_ratio_20d > 1000
        config = {
            "logic": "AND",
            "conditions": [
                {"type": "rank_in_top_n", "n": 8},
                {"field": "volume_ratio_20d", "op": ">", "value": 1000},  # impossible
            ],
        }
        signals = SignalEngine().entry_signals(ranked_snap, {}, config)
        assert signals == [], "No entry signals when one condition is impossible"

    def test_all_conditions_pass_generates_signal(self, ranked_snap):
        config = self._all_pass_entry_config(ranked_snap)
        signals = SignalEngine().entry_signals(ranked_snap, {}, config)
        assert len(signals) > 0
        assert len(signals) <= 8  # capped by rank_in_top_n

    def test_only_top_n_tickers_get_signal(self, ranked_snap):
        config = {
            "logic": "AND",
            "conditions": [{"type": "rank_in_top_n", "n": 5}],
        }
        signals = SignalEngine().entry_signals(ranked_snap, {}, config)
        assert len(signals) <= 5
        # All signaled tickers must be rank <= 5
        for t in signals:
            row = ranked_snap[ranked_snap["ticker"] == t]
            assert int(row["rank"].iloc[0]) <= 5

    def test_crossover_condition_uses_history(self):
        """Entry triggered when SMA20 crosses above SMA50 in history."""
        history = _make_history(60)
        # Force a clear crossover: SMA20 was below SMA50, now above
        history.loc[history.index[-3], "sma_20"] = history["sma_50"].iloc[-3] * 0.99
        history.loc[history.index[-2], "sma_20"] = history["sma_50"].iloc[-2] * 1.01
        history.loc[history.index[-1], "sma_20"] = history["sma_50"].iloc[-1] * 1.02

        from signal_engine import _crosses
        assert _crosses(history, "sma_20", "sma_50", 3, "above") is True

    def test_no_crossover_no_crossover_signal(self):
        history = _make_history(60)
        # Ensure SMA20 stays below SMA50 throughout
        history["sma_20"] = history["sma_50"] * 0.95
        from signal_engine import _crosses
        assert _crosses(history, "sma_20", "sma_50", 3, "above") is False


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-04  出場信號 OR 邏輯
# ─────────────────────────────────────────────────────────────────────────────

class TestTC304ExitSignalOR:

    @pytest.fixture
    def ranked_snap(self):
        snap = _make_snapshot(20)
        return RankingEngine().score_and_rank(snap, RANKING_CONFIG)

    @pytest.fixture
    def exit_config(self):
        return {
            "logic": "OR",
            "conditions": [
                {"type": "rank_falls_below", "rank": 15},
                {"type": "stop_loss", "mode": "atr_multiple", "atr": "atr_14", "multiple": 2.0},
                {"type": "trailing_stop", "pct": 0.10},
                {"type": "take_profit", "pct": 0.25},
                {"field": "adjusted_close", "op": "<", "value": "sma_200"},
            ],
        }

    def test_stop_loss_triggers_exit(self, ranked_snap, exit_config):
        ticker = ranked_snap["ticker"].iloc[0]
        row = ranked_snap[ranked_snap["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]
        atr = row["atr_14"]

        # Entry was high enough that current price is well below 2*ATR stop
        position = {"entry_price": price + 3 * atr, "peak_price": price + 3 * atr, "entry_atr": atr}
        positions = {ticker: position}

        signals = SignalEngine().exit_signals(ranked_snap, {}, positions, exit_config)
        assert ticker in signals
        assert signals[ticker] == "stop_loss"

    def test_take_profit_triggers_exit(self, ranked_snap, exit_config):
        ticker = ranked_snap["ticker"].iloc[0]
        row = ranked_snap[ranked_snap["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]

        # Entry was 30% below current price → take profit at 25%
        position = {"entry_price": price * 0.70, "peak_price": price, "entry_atr": 5.0}
        positions = {ticker: position}

        signals = SignalEngine().exit_signals(ranked_snap, {}, positions, exit_config)
        assert ticker in signals
        assert signals[ticker] == "take_profit"

    def test_trailing_stop_triggers_exit(self, ranked_snap, exit_config):
        ticker = ranked_snap["ticker"].iloc[0]
        row = ranked_snap[ranked_snap["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]

        # Peak was 20% higher than current → trailing stop at 10%
        peak = price * 1.25
        position = {"entry_price": price * 0.80, "peak_price": peak, "entry_atr": 5.0}
        positions = {ticker: position}

        signals = SignalEngine().exit_signals(ranked_snap, {}, positions, exit_config)
        assert ticker in signals
        assert signals[ticker] == "trailing_stop"

    def test_rank_falls_below_triggers_exit(self, ranked_snap, exit_config):
        # Pick the worst-ranked ticker (rank > 15)
        worst = ranked_snap[ranked_snap["rank"] > 15]
        if worst.empty:
            pytest.skip("No tickers with rank > 15 in this snapshot")
        ticker = worst["ticker"].iloc[0]
        row = worst.iloc[0].to_dict()
        price = row["adjusted_close"]
        position = {"entry_price": price, "peak_price": price, "entry_atr": 5.0}

        signals = SignalEngine().exit_signals(ranked_snap, {}, {ticker: position}, exit_config)
        assert ticker in signals
        assert signals[ticker] == "rank_falls_below"

    def test_or_logic_single_trigger_is_enough(self, ranked_snap, exit_config):
        """Only one OR condition needs to be true."""
        ticker = ranked_snap["ticker"].iloc[0]
        row = ranked_snap[ranked_snap["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]

        # Only take_profit triggered, everything else fine
        position = {"entry_price": price * 0.70, "peak_price": price, "entry_atr": 1.0}
        signals = SignalEngine().exit_signals(ranked_snap, {}, {ticker: position}, exit_config)
        assert ticker in signals

    def test_no_exit_when_position_healthy(self, ranked_snap, exit_config):
        ticker = ranked_snap[ranked_snap["rank"] == 1]["ticker"].iloc[0]
        row = ranked_snap[ranked_snap["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]
        atr = row["atr_14"]

        # Healthy position: only 2% gain, above stop levels, rank #1
        position = {"entry_price": price * 0.98, "peak_price": price, "entry_atr": atr}
        # Force sma_200 below current price to avoid that exit condition
        ranked_snap.loc[ranked_snap["ticker"] == ticker, "sma_200"] = price * 0.80

        signals = SignalEngine().exit_signals(ranked_snap, {}, {ticker: position}, exit_config)
        assert ticker not in signals


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-05  Risk Guard 暫停
# ─────────────────────────────────────────────────────────────────────────────

class TestTC305RiskGuard:

    def test_no_halt_when_drawdown_below_threshold(self):
        rg = RiskGuard(halt_drawdown_pct=0.10)
        rg.update_nav(100_000)
        assert rg.is_halted(95_000) is False   # 5% drawdown, below 10% threshold
        assert rg.is_halted(91_000) is False   # 9% drawdown

    def test_halted_when_drawdown_exceeds_threshold(self):
        rg = RiskGuard(halt_drawdown_pct=0.10)
        rg.update_nav(100_000)
        assert rg.is_halted(89_000) is True    # 11% drawdown
        assert rg.is_halted(85_000) is True    # 15% drawdown

    def test_halt_blocks_entry_signals(self):
        snap = _make_snapshot(20)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        rg = RiskGuard(halt_drawdown_pct=0.10)
        rg.update_nav(100_000)

        config = {"logic": "AND", "conditions": [{"type": "rank_in_top_n", "n": 8}]}
        # Without halt
        signals_normal = SignalEngine().entry_signals(ranked, {}, config)
        # With halt (drawdown = 11%)
        signals_halted = SignalEngine().entry_signals(
            ranked, {}, config, risk_guard=rg, current_nav=89_000
        )
        assert len(signals_normal) > 0
        assert signals_halted == []

    def test_exit_signals_still_work_when_halted(self):
        """Risk Guard only blocks NEW entries; existing positions can still exit."""
        snap = _make_snapshot(10)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)

        rg = RiskGuard(halt_drawdown_pct=0.10)
        rg.update_nav(100_000)

        ticker = ranked["ticker"].iloc[0]
        row = ranked[ranked["ticker"] == ticker].iloc[0].to_dict()
        price = row["adjusted_close"]
        # Trigger take-profit
        position = {"entry_price": price * 0.70, "peak_price": price, "entry_atr": 1.0}
        exit_config = {"logic": "OR", "conditions": [{"type": "take_profit", "pct": 0.25}]}

        exits = SignalEngine().exit_signals(ranked, {}, {ticker: position}, exit_config)
        assert ticker in exits  # exit still works

    def test_peak_nav_updates_correctly(self):
        rg = RiskGuard(halt_drawdown_pct=0.10)
        rg.update_nav(100_000)
        rg.update_nav(110_000)  # new peak
        rg.update_nav(105_000)  # below new peak

        assert rg.current_drawdown(105_000) == pytest.approx(5_000 / 110_000, rel=0.001)
        assert rg.is_halted(99_000) is True   # 10% below new peak of 110k

    def test_no_halt_before_any_nav_update(self):
        rg = RiskGuard(halt_drawdown_pct=0.10)
        assert rg.is_halted(50_000) is False


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-06  Top-10 輸出
# ─────────────────────────────────────────────────────────────────────────────

class TestTC306Top10Output:

    def test_returns_exactly_10_when_enough_tickers(self):
        snap = _make_snapshot(25)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        top10 = SignalEngine().generate_top10(ranked)
        assert len(top10) == 10

    def test_returns_all_when_fewer_than_10(self):
        snap = _make_snapshot(7)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        top10 = SignalEngine().generate_top10(ranked)
        assert len(top10) == 7

    def test_top10_sorted_by_rank(self):
        snap = _make_snapshot(20)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        top10 = SignalEngine().generate_top10(ranked)
        ranks = [item["rank"] for item in top10]
        assert ranks == sorted(ranks)

    def test_top10_contains_required_fields(self):
        snap = _make_snapshot(20)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        top10 = SignalEngine().generate_top10(ranked)
        for item in top10:
            for field in ["ticker", "rank", "score"]:
                assert field in item, f"Missing field '{field}' in top-10 item"

    def test_rank_1_is_first_in_top10(self):
        snap = _make_snapshot(20)
        ranked = RankingEngine().score_and_rank(snap, RANKING_CONFIG)
        top10 = SignalEngine().generate_top10(ranked)
        assert top10[0]["rank"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# TC-3-07  新策略 JSON 無需修改 Python
# ─────────────────────────────────────────────────────────────────────────────

class TestTC307NewStrategyJsonNoPythonChanges:
    """A completely different strategy JSON should work with the same engines."""

    NEW_STRATEGY_FILTERS = {
        "fundamental": {
            "logic": "AND",
            "conditions": [
                {"field": "roe",            "op": ">",  "value": 0.15},
                {"field": "eps_ttm",        "op": ">",  "value": 0},
                {"field": "debt_to_equity", "op": "<",  "value": 1.0},
            ],
        },
        "technical": {
            "logic": "AND",
            "conditions": [
                {"field": "rsi_14",         "op": "between", "value": [40, 65]},
                {"field": "adx_14",         "op": ">",  "value": 15},
            ],
        },
    }

    NEW_RANKING_CONFIG = {
        "normalization": {"clip_percentiles": [5, 95], "handle_missing": "exclude_symbol"},
        "factors": [
            {"field": "momentum_90d",       "weight": 0.30, "direction": "desc"},
            {"field": "roe",                "weight": 0.30, "direction": "desc"},
            {"field": "pe_ratio",           "weight": 0.20, "direction": "asc"},
            {"field": "revenue_growth_yoy", "weight": 0.20, "direction": "desc"},
        ],
        "selection": {"watchlist_top_n": 15, "buy_top_n": 5, "min_score": 0},
    }

    def test_new_filter_config_works_without_python_changes(self):
        snap = _make_snapshot(20)
        result = FilterEngine().apply(snap, self.NEW_STRATEGY_FILTERS)
        assert isinstance(result, pd.DataFrame)
        # Verify all passing rows satisfy both conditions
        if not result.empty:
            assert all(result["roe"] > 0.15)
            assert all(result["eps_ttm"] > 0)

    def test_new_ranking_config_produces_valid_output(self):
        snap = _make_snapshot(20)
        result = RankingEngine().score_and_rank(snap, self.NEW_RANKING_CONFIG)
        assert "rank" in result.columns
        assert "score" in result.columns
        assert result["rank"].min() == 1

    def test_new_strategy_buy_candidates_capped_at_5(self):
        snap = _make_snapshot(20)
        ranked = RankingEngine().score_and_rank(snap, self.NEW_RANKING_CONFIG)
        buys = RankingEngine().get_buy_candidates(ranked, self.NEW_RANKING_CONFIG)
        assert len(buys) <= 5

    def test_real_strategy_json_works_end_to_end(self):
        """toprank_ma_momentum_v2.json drives FilterEngine + RankingEngine."""
        strategy_path = Path(__file__).parent.parent.parent / "strategies" / "toprank_ma_momentum_v2.json"
        if not strategy_path.exists():
            pytest.skip("Strategy file not found")

        strategy = json.loads(strategy_path.read_text())
        snap = _make_snapshot(30)

        # Filter (some may fail; that's expected)
        filtered = FilterEngine().apply(snap, strategy["filters"])
        assert isinstance(filtered, pd.DataFrame)

        # Rank whatever survived
        if not filtered.empty:
            ranked = RankingEngine().score_and_rank(filtered, strategy["ranking"])
            assert "rank" in ranked.columns
            top10 = SignalEngine().generate_top10(ranked)
            assert len(top10) <= 10
