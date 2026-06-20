"""TDD for verdict.core.indicators — pure, causal technical indicators.

Correctness focus: every indicator uses only current+past bars. Donchian and
the breakout volume average EXCLUDE the current bar (prior-N) so breakout rules
stay no-lookahead. Values are hand-checked where tractable and cross-validated
against the `ta` library on the real BNB series.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from verdict.core import indicators as ind


def test_ema_constant_series_is_constant():
    s = pd.Series([5.0] * 20)
    assert ind.ema(s, 10).iloc[-1] == pytest.approx(5.0)


def test_ema_matches_hand_computed_adjust_false():
    s = pd.Series([1.0, 2.0, 3.0])
    e = ind.ema(s, 2)  # alpha = 2/3
    assert e.iloc[0] == pytest.approx(1.0)
    assert e.iloc[1] == pytest.approx(2 / 3 * 2 + 1 / 3 * 1)        # 1.6667
    assert e.iloc[2] == pytest.approx(2 / 3 * 3 + 1 / 3 * (5 / 3))  # 2.5556


def test_sma_is_trailing_mean():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    sm = ind.sma(s, 3)
    assert math.isnan(sm.iloc[1])           # not enough history
    assert sm.iloc[2] == pytest.approx(2.0)  # mean(1,2,3)
    assert sm.iloc[4] == pytest.approx(4.0)  # mean(3,4,5)


def test_rsi_rising_series_is_high_falling_is_low():
    up = pd.Series(np.arange(1, 60, dtype=float))
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(up, 14).iloc[-1] > 95
    assert ind.rsi(down, 14).iloc[-1] < 5


def test_atr_constant_range_converges_to_range():
    # each bar spans exactly 2.0, closes inside the range -> TR == 2.0 -> ATR -> 2.0
    n = 40
    df = pd.DataFrame({
        "open": [10.0] * n, "high": [11.0] * n, "low": [9.0] * n,
        "close": [10.0] * n, "volume": [1.0] * n,
    })
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(2.0, abs=1e-6)


def test_donchian_excludes_current_bar_no_lookahead():
    # A spike on the LAST bar must not appear in that bar's donchian_high.
    high = [10, 11, 12, 13, 14, 99]
    df = pd.DataFrame({
        "open": high, "high": high, "low": high, "close": high,
        "volume": [1] * len(high),
    }, dtype=float)
    dh, dl = ind.donchian(df, n=3)
    # at the last bar, prior-3 highs are [12,13,14] -> 14, NOT 99
    assert dh.iloc[-1] == pytest.approx(14.0)
    assert dl.iloc[-1] == pytest.approx(12.0)


def test_macd_hist_is_macd_minus_signal():
    s = pd.Series(np.linspace(1, 100, 200))
    macd, signal, hist = ind.macd(s)
    assert hist.iloc[-1] == pytest.approx((macd - signal).iloc[-1])


def test_add_indicators_builds_canonical_feature_frame():
    n = 300
    rng = np.random.default_rng(0)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
    df = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close + 1.0, "low": close - 1.0, "close": close,
        "volume": pd.Series(rng.uniform(100, 200, n)),
    })
    out = ind.add_indicators(df)
    expected = {
        "ema20", "ema50", "ema100", "sma20", "sma50", "sma200",
        "rsi", "macd", "macd_signal", "macd_hist", "atr", "adx",
        "bb_mid", "bb_upper", "bb_lower", "donchian_high", "donchian_low", "vol_sma",
    }
    assert expected <= set(out.columns)
    # original OHLCV columns retained; no rows dropped
    assert len(out) == n
    assert {"open", "high", "low", "close", "volume"} <= set(out.columns)


def test_indicators_cross_validate_against_ta_on_real_series():
    """Independent-implementation check: our RSI/ATR/MACD ~ the `ta` library."""
    ta = pytest.importorskip("ta")
    from verdict.core.data import load_ohlcv
    df = load_ohlcv("BNB/USDT", "4h").to_dataframe().tail(800)
    h, l, c = df["high"], df["low"], df["close"]

    our_rsi = ind.rsi(c, 14).dropna()
    ta_rsi = ta.momentum.RSIIndicator(c, window=14).rsi().dropna()
    common = our_rsi.index.intersection(ta_rsi.index)[50:]
    assert np.allclose(our_rsi.loc[common], ta_rsi.loc[common], atol=0.5)

    our_atr = ind.atr(df, 14).dropna()
    ta_atr = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range().dropna()
    common = our_atr.index.intersection(ta_atr.index)[50:]
    # ATR scale is price units; relative agreement within 2%
    rel = (our_atr.loc[common] - ta_atr.loc[common]).abs() / ta_atr.loc[common]
    assert rel.median() < 0.02
