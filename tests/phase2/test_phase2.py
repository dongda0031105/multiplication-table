"""
Phase 2 Test Suite — 6 test cases (TC-2-01 through TC-2-06)

Run:  pytest tests/phase2/ -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from data_pipeline import DataPipeline, FileCache
from derived_factor_engine import DerivedFactorEngine, FormulaError
from indicator_engine import IndicatorEngine, IndicatorError
from universe_filter import UniverseFilter

from tests.phase2.fixtures import (
    make_derived_factor_list,
    make_fundamentals,
    make_indicator_list,
    make_ohlcv,
)

# ─────────────────────────────────────────────────────────────────────────────
# TC-2-01  OHLCV 拉取完整性
# ─────────────────────────────────────────────────────────────────────────────

class TestTC201OHLCVFetch:
    """fetch_ohlcv returns a complete, NaN-free DataFrame with all required columns."""

    def _make_pipeline(self, tmp_path, df: pd.DataFrame) -> DataPipeline:
        dp = DataPipeline(cache_dir=str(tmp_path / "cache"))
        dp._fetch_bars_from_api = MagicMock(return_value=df)
        return dp

    def test_all_required_columns_present(self, tmp_path):
        df = make_ohlcv()
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        for col in ["open", "high", "low", "close", "adjusted_close", "volume"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_nan_in_synthetic_data(self, tmp_path):
        df = make_ohlcv(n_days=300)
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        assert not result.isnull().any().any(), "OHLCV should have no NaN values"

    def test_at_least_260_rows(self, tmp_path):
        df = make_ohlcv(n_days=300)
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        assert len(result) >= 260, f"Expected ≥260 rows, got {len(result)}"

    def test_index_is_datetimeindex(self, tmp_path):
        df = make_ohlcv()
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_volume_is_positive(self, tmp_path):
        df = make_ohlcv()
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        assert (result["volume"] > 0).all(), "All volume values must be positive"

    def test_high_gte_low(self, tmp_path):
        df = make_ohlcv()
        dp = self._make_pipeline(tmp_path, df)
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        assert (result["high"] >= result["low"]).all(), "high must be ≥ low"


# ─────────────────────────────────────────────────────────────────────────────
# TC-2-02  指標計算正確性
# ─────────────────────────────────────────────────────────────────────────────

class TestTC202IndicatorAccuracy:
    """Indicator values must match known reference formulas within 0.01%."""

    @pytest.fixture
    def df_with_indicators(self):
        df = make_ohlcv(n_days=300)
        engine = IndicatorEngine()
        return engine.compute(df, make_indicator_list())

    def test_sma20_matches_pandas_rolling(self, df_with_indicators):
        df = df_with_indicators
        ref = df["adjusted_close"].rolling(20).mean()
        # Compare only non-NaN values
        mask = ref.notna()
        diff = (df["sma_20"][mask] - ref[mask]).abs() / ref[mask].abs()
        assert (diff < 1e-4).all(), f"SMA20 max deviation: {diff.max():.6f}"

    def test_sma50_matches_pandas_rolling(self, df_with_indicators):
        df = df_with_indicators
        ref = df["adjusted_close"].rolling(50).mean()
        mask = ref.notna()
        diff = (df["sma_50"][mask] - ref[mask]).abs() / ref[mask].abs()
        assert (diff < 1e-4).all()

    def test_ema20_matches_pandas_ewm(self, df_with_indicators):
        df = df_with_indicators
        ref = df["adjusted_close"].ewm(span=20, adjust=False).mean()
        mask = ref.notna()
        diff = (df["ema_20"][mask] - ref[mask]).abs() / ref[mask].abs()
        assert (diff < 1e-4).all()

    def test_rsi_bounded_0_to_100(self, df_with_indicators):
        rsi = df_with_indicators["rsi_14"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all(), \
            f"RSI out of range: min={rsi.min():.2f} max={rsi.max():.2f}"

    def test_rsi_nan_for_first_period_minus_one_rows(self):
        df = make_ohlcv(n_days=50)
        result = IndicatorEngine().compute(df, [
            {"name": "rsi_14", "type": "RSI", "source": "adjusted_close", "period": 14}
        ])
        # RSI needs period rows of diff → first (period) rows may be NaN
        assert result["rsi_14"].iloc[:14].isna().any(), \
            "RSI should be NaN for initial rows"

    def test_macd_three_outputs_present(self, df_with_indicators):
        for col in ["macd_line", "macd_signal", "macd_histogram"]:
            assert col in df_with_indicators.columns

    def test_macd_histogram_equals_line_minus_signal(self, df_with_indicators):
        df = df_with_indicators
        mask = df["macd_line"].notna()
        diff = (df["macd_histogram"][mask] - (df["macd_line"][mask] - df["macd_signal"][mask])).abs()
        assert (diff < 1e-10).all()

    def test_bollinger_upper_gte_middle_gte_lower(self, df_with_indicators):
        df = df_with_indicators.dropna(subset=["bb_upper", "bb_middle", "bb_lower"])
        assert (df["bb_upper"] >= df["bb_middle"]).all()
        assert (df["bb_middle"] >= df["bb_lower"]).all()

    def test_atr_is_positive(self, df_with_indicators):
        atr = df_with_indicators["atr_14"].dropna()
        assert (atr > 0).all(), "ATR must be positive"

    def test_adx_bounded_0_to_100(self, df_with_indicators):
        adx = df_with_indicators["adx_14"].dropna()
        assert (adx >= 0).all() and (adx <= 100).all(), \
            f"ADX out of range: min={adx.min():.2f} max={adx.max():.2f}"

    def test_obv_is_monotonic_with_volume(self):
        """OBV should increase when price rises and decrease when it falls."""
        df = make_ohlcv(n_days=100, seed=99)
        result = IndicatorEngine().compute(df, [{"name": "obv", "type": "OBV"}])
        # On rising bars, OBV delta should be positive
        rising = df["adjusted_close"].diff() > 0
        obv_delta = result["obv"].diff()
        assert (obv_delta[rising].dropna() > 0).all()


# ─────────────────────────────────────────────────────────────────────────────
# TC-2-03  動態指標載入（JSON 驅動，不修改 Python）
# ─────────────────────────────────────────────────────────────────────────────

class TestTC203DynamicIndicatorLoading:
    """IndicatorEngine reads the indicators list from JSON at runtime."""

    def test_adding_indicator_to_json_adds_column(self):
        df = make_ohlcv(n_days=250)
        engine = IndicatorEngine()

        # Base: only SMA20
        base_inds = [{"name": "sma_20", "type": "SMA", "source": "adjusted_close", "period": 20}]
        result_base = engine.compute(df, base_inds)
        assert "sma_100" not in result_base.columns

        # Extended: add SMA100 — no Python changes
        extended_inds = base_inds + [
            {"name": "sma_100", "type": "SMA", "source": "adjusted_close", "period": 100}
        ]
        result_ext = engine.compute(df, extended_inds)
        assert "sma_100" in result_ext.columns

    def test_empty_indicator_list_returns_unchanged_df(self):
        df = make_ohlcv(n_days=100)
        result = IndicatorEngine().compute(df, [])
        assert list(result.columns) == list(df.columns)

    def test_unknown_indicator_type_raises_error(self):
        df = make_ohlcv(n_days=100)
        with pytest.raises(IndicatorError, match="Unknown indicator type"):
            IndicatorEngine().compute(df, [{"name": "x", "type": "UNKNOWN_TYPE"}])

    def test_real_strategy_indicators_all_computed(self):
        """All indicators defined in toprank_ma_momentum_v2.json must be computed."""
        import json
        strategy_path = (
            Path(__file__).parent.parent.parent / "strategies" / "toprank_ma_momentum_v2.json"
        )
        if not strategy_path.exists():
            pytest.skip("Strategy file not found")

        strategy = json.loads(strategy_path.read_text())
        indicators = strategy["indicators"]

        df = make_ohlcv(n_days=300)
        result = IndicatorEngine().compute(df, indicators)

        expected_names = set()
        for ind in indicators:
            if "outputs" in ind:
                expected_names.update(ind["outputs"])
            else:
                expected_names.add(ind["name"])

        for col in expected_names:
            assert col in result.columns, f"Expected indicator column '{col}' not found"


# ─────────────────────────────────────────────────────────────────────────────
# TC-2-04  P/E Ratio 計算
# ─────────────────────────────────────────────────────────────────────────────

class TestTC204PERatioCalculation:
    """P/E = price / eps_ttm; EPS ≤ 0 → None."""

    def _make_pipeline_with_mock_yf(self, tmp_path, eps: float, price: float) -> DataPipeline:
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = {
            "trailingEps": eps,
            "currentPrice": price,
            "marketCap": 1_000_000_000,
            "sector": "Technology",
            "industry": "Software",
            "revenueGrowth": 0.15,
            "returnOnEquity": 0.20,
            "grossMargins": 0.65,
            "debtToEquity": 0.5,
            "averageVolume": 2_000_000,
        }
        return DataPipeline(cache_dir=str(tmp_path / "cache"), _yf=mock_yf)

    def test_positive_eps_computes_pe(self, tmp_path):
        dp = self._make_pipeline_with_mock_yf(tmp_path, eps=5.0, price=150.0)
        result = dp.fetch_fundamentals("AAPL")
        assert result["pe_ratio"] == pytest.approx(30.0, rel=0.01)

    def test_negative_eps_returns_none(self, tmp_path):
        dp = self._make_pipeline_with_mock_yf(tmp_path, eps=-2.0, price=50.0)
        result = dp.fetch_fundamentals("LOSS")
        assert result["pe_ratio"] is None

    def test_zero_eps_returns_none(self, tmp_path):
        dp = self._make_pipeline_with_mock_yf(tmp_path, eps=0.0, price=50.0)
        result = dp.fetch_fundamentals("ZERO")
        assert result["pe_ratio"] is None

    def test_pe_formula_matches_price_over_eps(self, tmp_path):
        eps, price = 8.5, 255.0
        dp = self._make_pipeline_with_mock_yf(tmp_path, eps=eps, price=price)
        result = dp.fetch_fundamentals("TEST")
        expected = round(price / eps, 2)
        assert result["pe_ratio"] == pytest.approx(expected, rel=0.001)

    def test_fundamentals_dict_has_required_fields(self, tmp_path):
        dp = self._make_pipeline_with_mock_yf(tmp_path, eps=5.0, price=150.0)
        result = dp.fetch_fundamentals("AAPL")
        for field in ["ticker", "market_cap", "sector", "pe_ratio", "eps_ttm", "roe"]:
            assert field in result, f"Missing field: {field}"


# ─────────────────────────────────────────────────────────────────────────────
# TC-2-05  Universe 篩選
# ─────────────────────────────────────────────────────────────────────────────

class TestTC205UniverseFiltering:
    """UniverseFilter correctly applies all universe and fundamental conditions."""

    @pytest.fixture
    def sample_tickers(self):
        return [
            make_fundamentals("TECH_BIG",   market_cap=50e9,  sector="Technology",  avg_volume=3_000_000),
            make_fundamentals("TECH_SMALL",  market_cap=500e6, sector="Technology",  avg_volume=500_000),   # < min_cap
            make_fundamentals("FINANCE_CO",  market_cap=20e9,  sector="Financials",  avg_volume=2_000_000), # excluded sector
            make_fundamentals("LOW_VOL_CO",  market_cap=5e9,   sector="Healthcare",  avg_volume=50_000),    # < min_vol
            make_fundamentals("UTILITY_CO",  market_cap=10e9,  sector="Utilities",   avg_volume=1_000_000), # excluded sector
            make_fundamentals("HEALTH_CO",   market_cap=8e9,   sector="Healthcare",  avg_volume=1_500_000),
        ]

    @pytest.fixture
    def universe_config(self):
        return {
            "min_market_cap": 2_000_000_000,
            "min_avg_volume_20d": 1_000_000,
            "exclude_sectors": ["Financials", "Utilities"],
        }

    def test_excludes_small_market_cap(self, sample_tickers, universe_config):
        uf = UniverseFilter()
        result = uf.filter_by_universe(sample_tickers, universe_config)
        tickers = [t["ticker"] for t in result]
        assert "TECH_SMALL" not in tickers

    def test_excludes_financial_sector(self, sample_tickers, universe_config):
        uf = UniverseFilter()
        result = uf.filter_by_universe(sample_tickers, universe_config)
        tickers = [t["ticker"] for t in result]
        assert "FINANCE_CO" not in tickers

    def test_excludes_utilities_sector(self, sample_tickers, universe_config):
        uf = UniverseFilter()
        result = uf.filter_by_universe(sample_tickers, universe_config)
        tickers = [t["ticker"] for t in result]
        assert "UTILITY_CO" not in tickers

    def test_excludes_low_volume(self, sample_tickers, universe_config):
        uf = UniverseFilter()
        result = uf.filter_by_universe(sample_tickers, universe_config)
        tickers = [t["ticker"] for t in result]
        assert "LOW_VOL_CO" not in tickers

    def test_passes_qualifying_tickers(self, sample_tickers, universe_config):
        uf = UniverseFilter()
        result = uf.filter_by_universe(sample_tickers, universe_config)
        tickers = [t["ticker"] for t in result]
        assert "TECH_BIG" in tickers
        assert "HEALTH_CO" in tickers

    def test_fundamental_filter_roe(self):
        tickers = [
            make_fundamentals("HIGH_ROE", roe=0.25),
            make_fundamentals("LOW_ROE",  roe=0.05),
        ]
        conditions = [{"field": "roe", "op": ">", "value": 0.10}]
        result = UniverseFilter().filter_by_fundamentals(tickers, conditions)
        tickers_out = [t["ticker"] for t in result]
        assert "HIGH_ROE" in tickers_out
        assert "LOW_ROE" not in tickers_out

    def test_fundamental_filter_missing_field_excluded(self):
        ticker_no_roe = {"ticker": "NO_ROE", "market_cap": 10e9}  # no roe key
        conditions = [{"field": "roe", "op": ">", "value": 0.10}]
        result = UniverseFilter().filter_by_fundamentals([ticker_no_roe], conditions)
        assert len(result) == 0

    def test_between_operator(self):
        tickers = [
            make_fundamentals("MID",  roe=0.15),
            make_fundamentals("HIGH", roe=0.40),
        ]
        conditions = [{"field": "roe", "op": "between", "value": [0.10, 0.30]}]
        result = UniverseFilter().filter_by_fundamentals(tickers, conditions)
        tickers_out = [t["ticker"] for t in result]
        assert "MID" in tickers_out
        assert "HIGH" not in tickers_out


# ─────────────────────────────────────────────────────────────────────────────
# TC-2-06  資料快取
# ─────────────────────────────────────────────────────────────────────────────

class TestTC206DataCaching:
    """FileCache prevents duplicate API calls within the same day."""

    def _make_pipeline(self, tmp_path) -> DataPipeline:
        df = make_ohlcv(n_days=300)
        dp = DataPipeline(cache_dir=str(tmp_path / "cache"))
        dp._fetch_bars_from_api = MagicMock(return_value=df)
        return dp

    def test_second_call_uses_cache(self, tmp_path):
        dp = self._make_pipeline(tmp_path)
        dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")  # second call
        assert dp._fetch_bars_from_api.call_count == 1

    def test_different_tickers_are_separate_cache_entries(self, tmp_path):
        dp = self._make_pipeline(tmp_path)
        dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        dp.fetch_ohlcv("MSFT", "2024-01-01", "2025-01-01")
        assert dp._fetch_bars_from_api.call_count == 2

    def test_cache_file_created_after_fetch(self, tmp_path):
        cache_dir = tmp_path / "cache"
        dp = self._make_pipeline(tmp_path)
        dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")
        cache_files = list(cache_dir.glob("*.json"))
        assert len(cache_files) == 1

    def test_cached_data_matches_original(self, tmp_path):
        df_original = make_ohlcv(n_days=300)
        dp = DataPipeline(cache_dir=str(tmp_path / "cache"))
        dp._fetch_bars_from_api = MagicMock(return_value=df_original)

        dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")  # writes cache
        result = dp.fetch_ohlcv("AAPL", "2024-01-01", "2025-01-01")  # reads cache

        pd.testing.assert_frame_equal(
            result.reset_index(drop=True),
            df_original.reset_index(drop=True),
            check_dtype=False,
        )

    def test_fundamentals_cache_prevents_duplicate_api_call(self, tmp_path):
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.info = {
            "trailingEps": 5.0, "currentPrice": 150.0,
            "marketCap": 3e12, "sector": "Technology", "industry": "Consumer Electronics",
            "revenueGrowth": 0.08, "returnOnEquity": 0.20,
            "grossMargins": 0.45, "debtToEquity": 0.5, "averageVolume": 3_000_000,
        }
        dp = DataPipeline(cache_dir=str(tmp_path / "cache"), _yf=mock_yf)
        dp.fetch_fundamentals("AAPL")
        dp.fetch_fundamentals("AAPL")
        assert mock_yf.Ticker.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: DerivedFactorEngine 驗證
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivedFactorEngine:
    """DerivedFactorEngine evaluates strategy JSON formula strings correctly."""

    @pytest.fixture
    def df_with_indicators(self):
        df = make_ohlcv(n_days=300)
        engine = IndicatorEngine()
        df2 = engine.compute(df, make_indicator_list())
        return df2

    def test_ma_gap_20_formula(self, df_with_indicators):
        df = DerivedFactorEngine().compute(
            df_with_indicators,
            [{"name": "ma_gap_20", "formula": "(adjusted_close - sma_20) / sma_20"}],
        )
        mask = df["sma_20"].notna()
        expected = (df["adjusted_close"][mask] - df["sma_20"][mask]) / df["sma_20"][mask]
        pd.testing.assert_series_equal(
            df["ma_gap_20"][mask].reset_index(drop=True),
            expected.reset_index(drop=True),
            check_names=False,
        )

    def test_lag_function_shifts_correctly(self, df_with_indicators):
        df = DerivedFactorEngine().compute(
            df_with_indicators,
            [{"name": "mom_20d", "formula": "(adjusted_close - lag(adjusted_close, 20)) / lag(adjusted_close, 20)"}],
        )
        assert "mom_20d" in df.columns
        assert df["mom_20d"].iloc[:20].isna().any()  # NaN at start due to lag

    def test_invalid_formula_raises_formula_error(self, df_with_indicators):
        with pytest.raises(FormulaError):
            DerivedFactorEngine().compute(
                df_with_indicators,
                [{"name": "bad", "formula": "nonexistent_column / adjusted_close"}],
            )

    def test_all_real_derived_factors_compute(self):
        """All derived_factors from toprank_ma_momentum_v2.json must compute.

        First compute ALL strategy indicators (so derived factors have their
        dependencies), then run the derived factor engine.
        """
        import json
        path = Path(__file__).parent.parent.parent / "strategies" / "toprank_ma_momentum_v2.json"
        if not path.exists():
            pytest.skip("Strategy file not found")
        strategy = json.loads(path.read_text())

        df = make_ohlcv(n_days=300)
        df_ind = IndicatorEngine().compute(df, strategy["indicators"])
        result = DerivedFactorEngine().compute(df_ind, strategy["derived_factors"])

        for factor in strategy["derived_factors"]:
            assert factor["name"] in result.columns, \
                f"Missing derived factor: {factor['name']}"
