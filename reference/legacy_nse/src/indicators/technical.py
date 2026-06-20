"""
Technical indicator computations using pandas/numpy.
All functions are pure — no side effects, no API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Individual indicator functions
# ---------------------------------------------------------------------------

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    # When avg_loss=0 (pure uptrend), RSI=100; when avg_gain=0 (pure downtrend), RSI=0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # Fix edge cases: avg_loss=0 → rs=inf → RSI=100; both 0 → rs=NaN → RSI=NaN → fill 50
    rsi = rsi.fillna(50.0)  # indeterminate 0/0 → neutral
    rsi = rsi.clip(0, 100)
    return rsi


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return close.ewm(span=period, adjust=False).mean()


def compute_vwap(high: pd.Series, low: pd.Series, close: pd.Series,
                 volume: pd.Series) -> pd.Series:
    """Volume-Weighted Average Price (cumulative, resets each day in caller)."""
    typical = (high + low + close) / 3
    cum_tp_vol = (typical * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, np.nan)
    return cum_tp_vol / cum_vol


def compute_vwap_bands(high: pd.Series, low: pd.Series, close: pd.Series,
                       volume: pd.Series, num_std: float = 1.5):
    """
    VWAP with standard deviation bands.

    Returns (vwap, upper, lower) Series.
    """
    typical = (high + low + close) / 3
    cum_tp_vol = (typical * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, np.nan)
    vwap = cum_tp_vol / cum_vol

    # Cumulative variance around VWAP
    cum_tp2_vol = (typical ** 2 * volume).cumsum()
    variance = cum_tp2_vol / cum_vol - vwap ** 2
    std = np.sqrt(variance.clip(lower=0))

    upper = vwap + num_std * std
    lower = vwap - num_std * std
    return vwap, upper, lower


def compute_bollinger_bands(close: pd.Series, period: int = 20,
                            std: float = 2.0):
    """Returns (upper, middle, lower) Bollinger Bands."""
    middle = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = middle + std * rolling_std
    lower = middle - std * rolling_std
    return upper, middle, lower


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26,
                 signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength."""
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() /
                     atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() /
                      atr.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return adx


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Aggregate dataclass + compute_all_indicators
# ---------------------------------------------------------------------------

@dataclass
class IndicatorValues:
    """Container for all computed indicators on a DataFrame."""
    rsi: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    vwap: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    vwap_upper: Optional[float] = None
    vwap_lower: Optional[float] = None
    adx: Optional[float] = None
    atr: Optional[float] = None


def compute_all_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> IndicatorValues:
    """
    Compute all indicators on a candle DataFrame and return the latest values.

    Expected df columns: open, high, low, close, volume
    Config keys: rsi_period, ema_fast, ema_slow, bb_period, bb_std,
                 macd_fast, macd_slow, macd_signal, adx_threshold (unused here)
    """
    if df is None or len(df) < 2:
        return IndicatorValues()

    c = df["close"]
    h = df["high"]
    lo = df["low"]

    iv = IndicatorValues()

    # RSI
    rsi_s = compute_rsi(c, config.get("rsi_period", 14))
    iv.rsi = _last(rsi_s)

    # EMA fast / slow
    ema_f = compute_ema(c, config.get("ema_fast", 9))
    ema_s = compute_ema(c, config.get("ema_slow", 21))
    iv.ema_fast = _last(ema_f)
    iv.ema_slow = _last(ema_s)

    # VWAP with bands (needs volume; skip if missing)
    if "volume" in df.columns and df["volume"].sum() > 0:
        vwap_s, vwap_u, vwap_l = compute_vwap_bands(h, lo, c, df["volume"])
        iv.vwap = _last(vwap_s)
        iv.vwap_upper = _last(vwap_u)
        iv.vwap_lower = _last(vwap_l)

    # Bollinger Bands
    bb_u, bb_m, bb_l = compute_bollinger_bands(
        c, config.get("bb_period", 20), config.get("bb_std", 2.0))
    iv.bb_upper = _last(bb_u)
    iv.bb_middle = _last(bb_m)
    iv.bb_lower = _last(bb_l)

    # MACD
    macd_l, sig_l, hist_l = compute_macd(
        c, config.get("macd_fast", 12), config.get("macd_slow", 26),
        config.get("macd_signal", 9))
    iv.macd = _last(macd_l)
    iv.macd_signal = _last(sig_l)
    iv.macd_histogram = _last(hist_l)

    # ADX
    adx_s = compute_adx(h, lo, c, period=14)
    iv.adx = _last(adx_s)

    # ATR
    atr_s = compute_atr(h, lo, c, period=14)
    iv.atr = _last(atr_s)

    return iv


def _last(s: pd.Series) -> Optional[float]:
    """Return last non-NaN value or None."""
    if s is None or s.empty:
        return None
    val = s.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)
