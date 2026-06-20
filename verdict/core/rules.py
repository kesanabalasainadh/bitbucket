"""
verdict.core.rules — the DETERMINISTIC RULE GRAMMAR.

This module is the single contract the strategy skill (WP-2) emits against: every
``entry_rules`` / ``exit_rules`` string a candidate produces is evaluated here,
1:1, against a strictly-causal feature frame. No LLM, no RNG, no I/O — pure,
deterministic boolean evaluation of human-readable rules.

Grammar (case-insensitive)
--------------------------
OPERANDS
  * base columns ............. close | open | high | low | volume
  * indicators (parse N) ..... ema_<N> | sma_<N> | rsi_<N> | atr_<N> | adx_<N>
                               donchian_high_<N> | donchian_low_<N> | vol_sma_<N>
  * fixed indicators ......... macd | macd_signal | macd_hist (12/26/9)
                               bb_upper | bb_lower | bb_mid (20, 2)
  * numbers .................. e.g. 65, 0.02, 1.5
  * scaled operand .......... "<col>*<k>" | "<col>+<k>" | "<col>-<k>"   (k a number)

RULE FORMS
  * "<lhs> > <rhs>"   ( also  <  >=  <=  == )
  * "<col> in [<a>,<b>]"                          e.g. "rsi_14 in [40,65]"
  * "<a> crosses_above <b>" | "<a> crosses_below <b>"      (t-1 vs t)
  * "abs(<a>-<b>)/<b> <= <p>"                     e.g. "abs(close-ema_20)/ema_20 <= 0.02"
  * "<col> rising" | "<col> falling"              (t vs t-1)

SEMANTICS
  ENTRY fires when ALL entry_rules are true on bar t close (logical AND); the
  backtester fills at the t+1 open. Any operand that is NaN at bar t (indicator
  not yet warmed up) makes its rule False — an unwarmed indicator never triggers
  an entry. Causality guarantee: every column is computed with only current+past
  bars, so the value at bar t is identical whether or not future bars exist — this
  is what makes the no-lookahead probe pass.

EXITS (helpers for the backtester)
  * ``parse_exit_level`` turns "1.5 * ATR(14)" / "2%" into a typed ExitLevel.
  * ``parse_max_hold`` reads "max_hold=<n> bars" out of exit_rules.
  * ``grammar_exit_rules`` keeps only the evaluable rule strings (drops max_hold
    and stop/target *definitions*), so the backtester can OR them as exit signals.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd

from verdict.core import indicators as ind

# --------------------------------------------------------------------------- #
# SUPPORTED — the machine-readable surface WP-2 matches its candidate strings to.
# --------------------------------------------------------------------------- #
SUPPORTED: dict[str, list[str]] = {
    "base_columns": ["close", "open", "high", "low", "volume", "sentiment_score", "velocity", "shock", "news_volume"],
    "parametric_indicators": [
        "ema_<N>", "sma_<N>", "rsi_<N>", "atr_<N>", "adx_<N>",
        "donchian_high_<N>", "donchian_low_<N>", "vol_sma_<N>",
    ],
    "fixed_indicators": ["macd", "macd_signal", "macd_hist", "bb_upper", "bb_lower", "bb_mid"],
    "operand_forms": ["<col>", "<number>", "<col>*<k>", "<col>+<k>", "<col>-<k>"],
    "rule_forms": [
        "<lhs> > <rhs>", "<lhs> < <rhs>", "<lhs> >= <rhs>", "<lhs> <= <rhs>", "<lhs> == <rhs>",
        "<col> in [<a>,<b>]",
        "<a> crosses_above <b>", "<a> crosses_below <b>",
        "abs(<a>-<b>)/<b> <= <p>",
        "<col> rising", "<col> falling",
    ],
    "exit_forms": ["<k> * ATR(<N>)", "<p>%", "max_hold=<n> bars", "<grammar rule>"],
}

_FLOAT = r"[-+]?\d*\.?\d+"
_ARITH_RE = re.compile(rf"^([a-z_][a-z0-9_]*)\s*([*+\-])\s*({_FLOAT})$")
_CMP_SPLIT_RE = re.compile(r"\s*(>=|<=|==|>|<)\s*")
_IN_RE = re.compile(rf"^(.+?)\s+in\s+\[\s*({_FLOAT})\s*,\s*({_FLOAT})\s*\]$")
_CROSS_RE = re.compile(r"^(.+?)\s+crosses_(above|below)\s+(.+?)$")
_RISEFALL_RE = re.compile(r"^(.+?)\s+(rising|falling)$")
_WITHIN_RE = re.compile(rf"^abs\(\s*(.+?)\s*-\s*(.+?)\s*\)\s*/\s*(.+?)\s*(<=|<)\s*({_FLOAT})$")

_EMA = re.compile(r"^ema_(\d+)$")
_SMA = re.compile(r"^sma_(\d+)$")
_RSI = re.compile(r"^rsi_(\d+)$")
_ATR = re.compile(r"^atr_(\d+)$")
_ADX = re.compile(r"^adx_(\d+)$")
_DONCH = re.compile(r"^donchian_(high|low)_(\d+)$")
_VOLSMA = re.compile(r"^vol_sma_(\d+)$")


# --------------------------------------------------------------------------- #
# Column resolution (strictly causal; memoized onto the frame)
# --------------------------------------------------------------------------- #
def _compute_column(df: pd.DataFrame, token: str) -> pd.Series:
    """Build one strictly-causal indicator column from its token.

    Value at bar t depends only on bars <= t (ewm/rolling/shift), so memoizing
    the whole column is safe for no-lookahead.
    """
    if token in ("close", "open", "high", "low", "volume", "sentiment_score", "velocity", "shock", "news_volume"):
        return df[token]
    if (m := _EMA.match(token)):
        return ind.ema(df["close"], int(m.group(1)))
    if (m := _SMA.match(token)):
        return ind.sma(df["close"], int(m.group(1)))
    if (m := _RSI.match(token)):
        return ind.rsi(df["close"], int(m.group(1)))
    if (m := _ATR.match(token)):
        return ind.atr(df, int(m.group(1)))
    if (m := _ADX.match(token)):
        return ind.adx(df, int(m.group(1)))
    if (m := _DONCH.match(token)):
        high, low = ind.donchian(df, int(m.group(2)))
        return high if m.group(1) == "high" else low
    if (m := _VOLSMA.match(token)):
        # prior-N mean volume (excludes the current bar) — keeps breakout
        # "volume > vol_sma_N * k" rules honest (no same-bar leak).
        return df["volume"].rolling(int(m.group(1))).mean().shift(1)
    if token in ("macd", "macd_signal", "macd_hist"):
        line, signal, hist = ind.macd(df["close"])
        return {"macd": line, "macd_signal": signal, "macd_hist": hist}[token]
    if token in ("bb_mid", "bb_upper", "bb_lower"):
        mid, upper, lower = ind.bollinger(df["close"], 20, 2.0)
        return {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower}[token]
    raise KeyError(f"unknown indicator token {token!r} (see verdict.core.rules.SUPPORTED)")


def _column(df: pd.DataFrame, token: str) -> pd.Series:
    if token not in df.columns:
        df[token] = _compute_column(df, token)
    return df[token]


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Return a *copy* of ``df`` to use as a working feature frame.

    Columns are materialized lazily on first reference (memoized onto the copy),
    so callers that loop over bars never recompute an indicator.
    """
    return df.copy()


def _operand_at(df: pd.DataFrame, operand: str, t: int) -> float:
    """Resolve an operand to its float value at bar ``t`` (NaN if unwarmed)."""
    s = operand.strip().lower()
    try:
        return float(s)                       # numeric literal
    except ValueError:
        pass
    if (m := _ARITH_RE.match(s)):             # "<col> <op> <k>"
        base = float(_column(df, m.group(1)).iloc[t])
        k = float(m.group(3))
        op = m.group(2)
        if op == "*":
            return base * k
        if op == "+":
            return base + k
        return base - k
    return float(_column(df, s).iloc[t])      # plain column


def _isnan(*vals: float) -> bool:
    return any(math.isnan(v) for v in vals)


def operand_value(df: pd.DataFrame, operand: str, t: int) -> float:
    """Public resolver: the float value of any grammar operand at bar ``t``.

    The backtester uses this to read e.g. ``atr_14`` at the signal bar when sizing
    a position and placing ATR-based stops/targets.
    """
    return _operand_at(df, operand, t)


# --------------------------------------------------------------------------- #
# Rule evaluation
# --------------------------------------------------------------------------- #
def evaluate_rule(df: pd.DataFrame, t: int, rule: str) -> bool:
    """Evaluate one grammar rule on bar ``t`` (positional). NaN operand -> False."""
    raw = rule.strip()
    low = raw.lower()

    # rising / falling  (t vs t-1)
    if (m := _RISEFALL_RE.match(low)):
        if t < 1:
            return False
        col = m.group(1).strip()
        now = _operand_at(df, col, t)
        prev = _operand_at(df, col, t - 1)
        if _isnan(now, prev):
            return False
        return bool(now > prev) if m.group(2) == "rising" else bool(now < prev)

    # crosses_above / crosses_below  (t-1 vs t)
    if (m := _CROSS_RE.match(low)):
        if t < 1:
            return False
        a, direction, b = m.group(1).strip(), m.group(2), m.group(3).strip()
        a0, a1 = _operand_at(df, a, t - 1), _operand_at(df, a, t)
        b0, b1 = _operand_at(df, b, t - 1), _operand_at(df, b, t)
        if _isnan(a0, a1, b0, b1):
            return False
        if direction == "above":
            return bool(a0 <= b0 and a1 > b1)
        return bool(a0 >= b0 and a1 < b1)

    # abs(a-b)/b <= p   (within-pct)
    if (m := _WITHIN_RE.match(low)):
        a, b, c = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        op, p = m.group(4), float(m.group(5))
        av, bv, cv = _operand_at(df, a, t), _operand_at(df, b, t), _operand_at(df, c, t)
        if _isnan(av, bv, cv) or cv == 0:
            return False
        ratio = abs(av - bv) / abs(cv)
        return bool(ratio <= p) if op == "<=" else bool(ratio < p)

    # col in [a, b]
    if (m := _IN_RE.match(low)):
        v = _operand_at(df, m.group(1).strip(), t)
        if _isnan(v):
            return False
        return bool(float(m.group(2)) <= v <= float(m.group(3)))

    # comparison  <lhs> <op> <rhs>
    parts = _CMP_SPLIT_RE.split(low, maxsplit=1)
    if len(parts) == 3:
        lhs, op, rhs = parts[0].strip(), parts[1], parts[2].strip()
        lv, rv = _operand_at(df, lhs, t), _operand_at(df, rhs, t)
        if _isnan(lv, rv):
            return False
        if op == ">":
            return bool(lv > rv)
        if op == "<":
            return bool(lv < rv)
        if op == ">=":
            return bool(lv >= rv)
        if op == "<=":
            return bool(lv <= rv)
        return bool(lv == rv)

    raise ValueError(f"unparseable rule {rule!r} (see verdict.core.rules.SUPPORTED)")


def rules_all(df: pd.DataFrame, t: int, rule_list: Iterable[str]) -> bool:
    """True iff EVERY rule is true at bar ``t``. Empty list -> False (no entry)."""
    rule_list = list(rule_list)
    if not rule_list:
        return False
    return all(evaluate_rule(df, t, r) for r in rule_list)


# --------------------------------------------------------------------------- #
# Exit-spec parsing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ExitLevel:
    """A parsed stop_loss / take_profit spec.

    kind == "atr" -> distance is ``k * ATR(n)`` price units from entry.
    kind == "pct" -> distance is ``k`` (a fraction, already /100) of entry price.
    """
    kind: str
    k: float
    n: int = 14


_ATR_SPEC = re.compile(rf"^({_FLOAT})\s*\*?\s*atr\s*\(\s*(\d+)\s*\)$")
_PCT_SPEC = re.compile(rf"^({_FLOAT})\s*%$")
_MAXHOLD = re.compile(r"max_hold\s*=\s*(\d+)")
_ASSIGN_DEF = re.compile(r"^(stop|target|sl|tp|max_hold)\b")


def parse_exit_level(spec: str) -> Optional[ExitLevel]:
    """Parse "<k> * ATR(<N>)" or "<p>%" into an ExitLevel; None if not a level."""
    s = (spec or "").strip().lower()
    if not s:
        return None
    if (m := _ATR_SPEC.match(s)):
        return ExitLevel("atr", float(m.group(1)), int(m.group(2)))
    if (m := _PCT_SPEC.match(s)):
        return ExitLevel("pct", float(m.group(1)) / 100.0)
    return None


def parse_max_hold(exit_rules: Iterable[str]) -> Optional[int]:
    """Read "max_hold=<n> bars" out of the exit_rules; None if absent."""
    for r in exit_rules:
        if (m := _MAXHOLD.search(r.lower())):
            return int(m.group(1))
    return None


def grammar_exit_rules(exit_rules: Iterable[str]) -> list[str]:
    """Keep only the evaluable grammar rules from exit_rules.

    Drops ``max_hold=...`` and ``stop=/target=`` *definitions* (those are handled
    structurally by the backtester), leaving rule strings like "rsi_14 > 70" that
    fire an exit signal at bar t close (filled at t+1 open).
    """
    out: list[str] = []
    for r in exit_rules:
        low = r.strip().lower()
        if not low or _MAXHOLD.search(low) or _ASSIGN_DEF.match(low):
            continue
        out.append(r.strip())
    return out
