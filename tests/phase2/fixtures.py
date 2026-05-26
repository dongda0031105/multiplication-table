"""Synthetic OHLCV + fundamental fixtures for Phase 2 tests."""
from typing import Dict, List

import numpy as np
import pandas as pd


def make_ohlcv(n_days: int = 300, seed: int = 42, base_price: float = 100.0) -> pd.DataFrame:
    """
    Generate realistic synthetic OHLCV data with a random-walk price.
    Returns DataFrame[open, high, low, close, adjusted_close, volume] with DatetimeIndex.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.015, n_days)
    prices = base_price * np.exp(np.cumsum(returns))

    noise = rng.normal(0, 0.003, n_days)
    opens = prices * (1 + noise)
    spread = rng.uniform(0.005, 0.02, n_days)
    highs = np.maximum(opens, prices) * (1 + spread * 0.5)
    lows = np.minimum(opens, prices) * (1 - spread * 0.5)
    volumes = rng.uniform(1_000_000, 5_000_000, n_days).astype(int)

    dates = pd.bdate_range(end=pd.Timestamp("2025-06-01"), periods=n_days)

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "adjusted_close": prices,
            "volume": volumes,
        },
        index=dates,
    )
    df.index.name = "date"
    return df


def make_fundamentals(
    ticker: str,
    market_cap: float = 50e9,
    sector: str = "Technology",
    eps: float = 5.0,
    price: float = 150.0,
    roe: float = 0.20,
    revenue_growth: float = 0.15,
    debt_to_equity: float = 0.5,
    avg_volume: float = 2_000_000,
) -> Dict:
    pe = round(price / eps, 2) if eps > 0 else None
    return {
        "ticker": ticker,
        "market_cap": market_cap,
        "sector": sector,
        "industry": "Software",
        "price": price,
        "pe_ratio": pe,
        "eps_ttm": eps,
        "revenue_growth_yoy": revenue_growth,
        "roe": roe,
        "gross_margin": 0.65,
        "debt_to_equity": debt_to_equity,
        "free_cash_flow_yield": 0.04,
        "avg_volume_20d": avg_volume,
    }


def make_indicator_list() -> List[Dict]:
    """Minimal indicator list for indicator engine tests."""
    return [
        {"name": "sma_20", "type": "SMA", "source": "adjusted_close", "period": 20},
        {"name": "sma_50", "type": "SMA", "source": "adjusted_close", "period": 50},
        {"name": "ema_20", "type": "EMA", "source": "adjusted_close", "period": 20},
        {"name": "rsi_14", "type": "RSI", "source": "adjusted_close", "period": 14},
        {
            "name": "macd", "type": "MACD", "source": "adjusted_close",
            "fast": 12, "slow": 26, "signal": 9,
            "outputs": ["macd_line", "macd_signal", "macd_histogram"],
        },
        {"name": "atr_14", "type": "ATR", "period": 14},
        {"name": "adx_14", "type": "ADX", "period": 14},
        {
            "name": "bb_20", "type": "BOLLINGER_BANDS",
            "source": "adjusted_close", "period": 20, "stddev": 2,
            "outputs": ["bb_upper", "bb_middle", "bb_lower"],
        },
        {"name": "avg_volume_20", "type": "SMA", "source": "volume", "period": 20},
        {"name": "obv", "type": "OBV"},
        {"name": "vwap", "type": "VWAP", "session": "daily"},
    ]


def make_derived_factor_list() -> List[Dict]:
    return [
        {"name": "ma_gap_20", "formula": "(adjusted_close - sma_20) / sma_20"},
        {"name": "ma_gap_50", "formula": "(adjusted_close - sma_50) / sma_50"},
        {"name": "momentum_20d", "formula": "(adjusted_close - lag(adjusted_close, 20)) / lag(adjusted_close, 20)"},
        {"name": "volume_ratio_20d", "formula": "volume / avg_volume_20"},
        {"name": "atr_pct", "formula": "atr_14 / adjusted_close"},
    ]
