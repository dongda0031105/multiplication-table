"""
IndicatorEngine — computes technical indicators from the strategy JSON
`indicators` array using pure pandas / numpy (no TA library dependency).

Adding a new indicator *instance* to a strategy only needs a JSON change.
Adding a new indicator *type* (e.g. "STOCH") requires adding a method here.
"""
from typing import Dict, List

import numpy as np
import pandas as pd


class IndicatorError(Exception):
    pass


class IndicatorEngine:

    def compute(self, df: pd.DataFrame, indicators: List[Dict]) -> pd.DataFrame:
        """Return a copy of df with all indicator columns appended."""
        result = df.copy()
        for ind in indicators:
            cols = self._dispatch(result, ind)
            for col_name, series in cols.items():
                result[col_name] = series
        return result

    # ── dispatch ──────────────────────────────────────────────────────────────

    _HANDLERS = {
        "SMA": "_sma", "EMA": "_ema", "RSI": "_rsi",
        "MACD": "_macd", "ADX": "_adx", "ATR": "_atr",
        "BOLLINGER_BANDS": "_bbands", "OBV": "_obv", "VWAP": "_vwap",
    }

    def _dispatch(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        itype = ind["type"].upper()
        handler_name = self._HANDLERS.get(itype)
        if handler_name is None:
            raise IndicatorError(f"Unknown indicator type: '{itype}'")
        return getattr(self, handler_name)(df, ind)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _src(df: pd.DataFrame, ind: Dict) -> pd.Series:
        col = ind.get("source", "adjusted_close")
        if col not in df.columns:
            raise IndicatorError(f"Source column '{col}' not found in DataFrame")
        return df[col]

    @staticmethod
    def _price(df: pd.DataFrame) -> pd.Series:
        return df["adjusted_close"] if "adjusted_close" in df.columns else df["close"]

    # ── single-output ─────────────────────────────────────────────────────────

    def _sma(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        return {ind["name"]: self._src(df, ind).rolling(ind["period"]).mean()}

    def _ema(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        return {
            ind["name"]: self._src(df, ind).ewm(
                span=ind["period"], adjust=False
            ).mean()
        }

    def _rsi(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        series = self._src(df, ind)
        period = ind["period"]
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        alpha = 1.0 / period
        avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        return {ind["name"]: rsi}

    def _obv(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        price = self._price(df)
        direction = np.sign(price.diff()).fillna(0)
        obv = (direction * df["volume"]).cumsum()
        return {ind["name"]: obv}

    def _vwap(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        price = self._price(df)
        typical = (df["high"] + df["low"] + price) / 3
        vwap = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
        return {ind["name"]: vwap}

    # ── multi-output ──────────────────────────────────────────────────────────

    def _macd(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        src = self._src(df, ind)
        fast, slow, sig = ind["fast"], ind["slow"], ind["signal"]
        outputs = ind.get("outputs", ["macd_line", "macd_signal", "macd_histogram"])

        ema_fast = src.ewm(span=fast, adjust=False).mean()
        ema_slow = src.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=sig, adjust=False).mean()
        histogram = macd_line - signal_line

        return {outputs[0]: macd_line, outputs[1]: signal_line, outputs[2]: histogram}

    def _atr(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        high, low = df["high"], df["low"]
        close = self._price(df)
        period = ind["period"]

        tr = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)

        atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        return {ind["name"]: atr}

    def _adx(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        high, low = df["high"], df["low"]
        close = self._price(df)
        period = ind["period"]
        alpha = 1.0 / period

        # True Range
        tr = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)

        # Directional Movement
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        plus_dm_s = pd.Series(plus_dm, index=df.index)
        minus_dm_s = pd.Series(minus_dm, index=df.index)

        # Wilder smoothing
        tr_s = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        plus_di = 100 * plus_dm_s.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr_s.replace(0, np.nan)
        minus_di = 100 * minus_dm_s.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / tr_s.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        return {ind["name"]: adx}

    def _bbands(self, df: pd.DataFrame, ind: Dict) -> Dict[str, pd.Series]:
        src = self._src(df, ind)
        period = ind["period"]
        stddev = ind.get("stddev", 2)
        outputs = ind.get("outputs", ["bb_upper", "bb_middle", "bb_lower"])

        middle = src.rolling(period).mean()
        std = src.rolling(period).std(ddof=1)
        return {
            outputs[0]: middle + stddev * std,
            outputs[1]: middle,
            outputs[2]: middle - stddev * std,
        }
