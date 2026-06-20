"""TDD for verdict.core.rules — the deterministic rule grammar.

This grammar is the *contract* the strategy skill (WP-2) emits against: every
candidate's entry/exit rule string must be evaluable here 1:1. Tests pin every
supported form, the strict-causal column resolver, and NaN-during-warmup safety
(a rule referencing an unwarmed indicator is False, never an entry).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from verdict.core import rules


def _df(close, *, high=None, low=None, open_=None, volume=None) -> pd.DataFrame:
    close = pd.Series(close, dtype=float)
    n = len(close)
    return pd.DataFrame({
        "open": (close if open_ is None else pd.Series(open_, dtype=float)).values,
        "high": ((close + 1) if high is None else pd.Series(high, dtype=float)).values,
        "low": ((close - 1) if low is None else pd.Series(low, dtype=float)).values,
        "close": close.values,
        "volume": (np.full(n, 1000.0) if volume is None else np.asarray(volume, float)),
    })


# --------------------------------------------------------------------------- #
# Operands
# --------------------------------------------------------------------------- #
def test_number_and_column_operands():
    df = _df([1, 2, 3])
    assert rules.evaluate_rule(df, 2, "close > 2")          # 3 > 2
    assert not rules.evaluate_rule(df, 0, "close > 2")      # 1 > 2


def test_all_comparison_operators():
    df = _df([10, 20, 30])
    assert rules.evaluate_rule(df, 1, "close >= 20")
    assert rules.evaluate_rule(df, 1, "close <= 20")
    assert not rules.evaluate_rule(df, 1, "close > 20")
    assert not rules.evaluate_rule(df, 1, "close < 20")


def test_arithmetic_operand_scaling():
    df = _df([100, 100, 100])
    assert rules.evaluate_rule(df, 1, "close <= close*1.02")
    assert not rules.evaluate_rule(df, 1, "close >= close*1.02")
    assert rules.evaluate_rule(df, 1, "close+5 > close")


def test_evaluate_rule_returns_plain_bool():
    df = _df([1, 2, 3])
    assert isinstance(rules.evaluate_rule(df, 2, "close > 1"), bool)


# --------------------------------------------------------------------------- #
# Parametric indicator columns (strictly causal)
# --------------------------------------------------------------------------- #
def test_parametric_ema_and_rsi_on_uptrend():
    df = _df(list(range(1, 60)))                # clean rising series
    assert rules.evaluate_rule(df, 58, "close > ema_20")
    assert rules.evaluate_rule(df, 58, "rsi_14 > 90")


def test_rsi_in_range_on_flat_series():
    df = _df([50.0] * 30)                        # dead-flat -> RSI == 50
    assert rules.evaluate_rule(df, 29, "rsi_14 in [40,60]")
    assert not rules.evaluate_rule(df, 29, "rsi_14 in [10,40]")


def test_donchian_and_vol_sma_columns_resolve():
    df = _df(list(range(20, 50)), volume=list(range(1, 31)))
    assert isinstance(rules.evaluate_rule(df, 29, "close > donchian_high_20"), bool)
    assert isinstance(rules.evaluate_rule(df, 29, "volume > vol_sma_20 * 1.5"), bool)


def test_macd_and_bollinger_columns_resolve():
    df = _df(list(np.linspace(1, 100, 120)))
    assert isinstance(rules.evaluate_rule(df, 119, "macd > macd_signal"), bool)
    assert isinstance(rules.evaluate_rule(df, 119, "close < bb_upper"), bool)


# --------------------------------------------------------------------------- #
# Crosses / within-pct / rising-falling
# --------------------------------------------------------------------------- #
def test_crosses_above_and_below():
    df = _df([10, 10, 10, 9, 9, 9, 12])
    assert rules.evaluate_rule(df, 6, "close crosses_above sma_3")
    assert not rules.evaluate_rule(df, 6, "close crosses_below sma_3")
    # mirror case: drop below
    df2 = _df([10, 10, 10, 11, 11, 11, 5])
    assert rules.evaluate_rule(df2, 6, "close crosses_below sma_3")


def test_crosses_needs_prior_bar():
    df = _df([1, 5])
    assert not rules.evaluate_rule(df, 0, "close crosses_above sma_3")  # t==0 guard


def test_within_pct_of_column():
    flat = _df([100.0] * 10)
    assert rules.evaluate_rule(flat, 9, "abs(close-ema_2)/ema_2 <= 0.02")
    spike = _df([100, 100, 100, 100, 200])
    assert not rules.evaluate_rule(spike, 4, "abs(close-ema_2)/ema_2 <= 0.02")


def test_rising_and_falling():
    df = _df([1, 2, 3, 2])
    assert rules.evaluate_rule(df, 2, "close rising")
    assert rules.evaluate_rule(df, 3, "close falling")
    assert not rules.evaluate_rule(df, 0, "close rising")        # t==0 guard


# --------------------------------------------------------------------------- #
# Warmup / NaN safety + AND semantics + case-insensitivity
# --------------------------------------------------------------------------- #
def test_unwarmed_indicator_is_false_not_entry():
    # Rolling indicators (sma/rsi/atr) are NaN until warmed (min_periods); a rule
    # referencing one must be False so an unwarmed indicator never opens a trade.
    # (EMA/MACD use adjust=False and warm immediately — that's the backtester's
    # trade_start warmup to manage, not a per-rule NaN guard.)
    df = _df([1, 2, 3])                          # too short for sma_20 / rsi_14
    assert not rules.evaluate_rule(df, 2, "close > sma_20")
    assert not rules.evaluate_rule(df, 2, "rsi_14 in [40,65]")


def test_rules_all_is_logical_and():
    df = _df([10, 20, 30])
    assert rules.rules_all(df, 2, ["close > 5", "close < 100"])
    assert not rules.rules_all(df, 2, ["close > 5", "close > 100"])
    assert not rules.rules_all(df, 2, [])        # no rules -> never enter


def test_case_insensitive():
    df = _df([1, 2, 3])
    assert rules.evaluate_rule(df, 2, "CLOSE > 2")
    assert rules.evaluate_rule(df, 2, "Close RISING")


# --------------------------------------------------------------------------- #
# Exit-spec parsing
# --------------------------------------------------------------------------- #
def test_parse_exit_level_atr_and_pct():
    e = rules.parse_exit_level("1.5 * ATR(14)")
    assert e.kind == "atr" and e.k == pytest.approx(1.5) and e.n == 14
    e2 = rules.parse_exit_level("3*atr(21)")
    assert e2.kind == "atr" and e2.k == pytest.approx(3.0) and e2.n == 21
    e3 = rules.parse_exit_level("2%")
    assert e3.kind == "pct" and e3.k == pytest.approx(0.02)
    assert rules.parse_exit_level("") is None
    assert rules.parse_exit_level("nonsense") is None


def test_parse_max_hold_and_grammar_exit_rules():
    rules_in = ["max_hold=10 bars", "rsi_14 > 70", "stop=entry-1.5*ATR"]
    assert rules.parse_max_hold(rules_in) == 10
    assert rules.parse_max_hold(["rsi_14 > 70"]) is None
    # only the evaluable grammar rule survives; max_hold and stop/target defs drop out
    assert rules.grammar_exit_rules(rules_in) == ["rsi_14 > 70"]


def test_supported_export_documents_the_grammar():
    assert isinstance(rules.SUPPORTED, dict)
    assert rules.SUPPORTED  # non-empty: WP-2 matches its candidate strings against this
