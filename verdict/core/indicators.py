"""
verdict.core.indicators — pure, causal technical indicators.

Every function uses ONLY current-and-past bars (no lookahead). Two functions
deliberately exclude the current bar so breakout rules stay honest:
  * ``donchian`` returns the prior-N high/low (max/min over [t-N, t-1]).
  * the ``vol_sma`` column is the prior-N mean volume (over [t-N, t-1]).

``add_indicators`` assembles the canonical feature frame that the rule DSL
(verdict.core.rules) reads by column name.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Moving averages
# --------------------------------------------------------------------------- #
def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential MA, adjust=False (recursive form): e_t = a*x_t + (1-a)*e_{t-1}."""
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


# --------------------------------------------------------------------------- #
# Oscillators
# --------------------------------------------------------------------------- #
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI. Flat segments (no gain & no loss) -> neutral 50."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing == EMA with alpha = 1/n
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0, 100.0)        # no losses -> 100
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # dead flat -> 50
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# --------------------------------------------------------------------------- #
# Volatility / trend strength
# --------------------------------------------------------------------------- #
def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR (RMA of true range)."""
    tr = _true_range(df)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ADX(n). Causal: directional movement + RMA smoothing."""
    high, low = df["high"], df["low"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    tr = _true_range(df)
    atr_n = tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / atr_n
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / atr_n
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def donchian(df: pd.DataFrame, n: int = 20):
    """Prior-N channel: max/min over [t-N, t-1] (EXCLUDES the current bar)."""
    prior_high = df["high"].rolling(n).max().shift(1)
    prior_low = df["low"].rolling(n).min().shift(1)
    return prior_high, prior_low


def rolling_return(close: pd.Series, n: int) -> pd.Series:
    """Return over the prior n bars measured at the previous close (excl current)."""
    return close.shift(1) / close.shift(1 + n) - 1.0


# --------------------------------------------------------------------------- #
# Canonical feature frame
# --------------------------------------------------------------------------- #
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` (open/high/low/close/volume) with the canonical
    indicator columns the rule DSL references by name."""
    out = df.copy()
    c = out["close"]
    for span in (20, 50, 100, 200):
        out[f"ema{span}"] = ema(c, span)
    for win in (20, 50, 200):
        out[f"sma{win}"] = sma(c, win)
    out["rsi"] = rsi(c, 14)
    m, s, h = macd(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = m, s, h
    out["atr"] = atr(out, 14)
    out["adx"] = adx(out, 14)
    bb_m, bb_u, bb_l = bollinger(c, 20, 2.0)
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = bb_m, bb_u, bb_l
    dh, dl = donchian(out, 20)
    out["donchian_high"], out["donchian_low"] = dh, dl
    out["vol_sma"] = out["volume"].rolling(20).mean().shift(1)  # prior-20, excl current
    out["ret63"] = rolling_return(c, 63)
    return out
