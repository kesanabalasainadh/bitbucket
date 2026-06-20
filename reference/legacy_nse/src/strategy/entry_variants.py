"""
Entry-redesign variants for the pre-registered 2026-06-11 grid.

All five generators expose the same ``generate_signal(symbol, df,
current_weekday=None)`` interface as ``SwingSignalGenerator`` so the
backtester can swap them without changing the loop.

No-lookahead contract (mirrored from the pre-registration doc):
  * Signal fires on day T close; fill is at T+1 open in the backtester.
  * df.index[-1] == day T. Any indicator that depends on STRICT T-1 data
    uses df.iloc[-2] or earlier (notably E2 RS and E3 breakout's prior
    20-day window).
  * E3/E4 compare *today's* volume against the average of the PRIOR 20
    days (not including today). This is the standard breakout definition
    and is documented as an audit anchor.

Filter rejections are recorded in each generator's ``rejected``
Counter so the experiment runner can report what each filter actually
did.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from src.indicators.technical import compute_atr
from src.strategy.swing_signal_generator import (
    SwingSignal, SwingSignalGenerator, SwingSignalType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — no-lookahead utilities
# ---------------------------------------------------------------------------

def _trend_filter_passes(df: pd.DataFrame) -> bool:
    """E1 stock-level trend: close > SMA(close, 200) AND SMA(close, 50)
    > SMA(close, 200). All computed up to and including day T close
    (the signal bar). Same convention as the baseline EMA generator,
    so no lookahead vs the existing logic.
    """
    if df is None or len(df) < 200:
        return False
    close = df["close"]
    sma200 = float(close.rolling(200).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    last_close = float(close.iloc[-1])
    return last_close > sma200 and sma50 > sma200


def _rs_filter_passes(df: pd.DataFrame,
                       nifty: Optional[pd.Series],
                       lookback: int = 63) -> bool:
    """E2 relative strength: stock's 63d return at T-1 close > Nifty's
    63d return at T-1 close.

    STRICT T-1: we never read close[-1] (T) for this filter.
    """
    if nifty is None or nifty.empty:
        return False
    if df is None or len(df) < lookback + 2:
        return False
    stock_close = df["close"]
    # T-1 close is iloc[-2]; the close lookback days before that is
    # iloc[-2 - lookback]. So we need at least lookback + 2 bars.
    s_t_minus_1 = float(stock_close.iloc[-2])
    s_old = float(stock_close.iloc[-2 - lookback])
    if s_old <= 0:
        return False
    stock_ret = s_t_minus_1 / s_old - 1.0

    # Nifty series is indexed by YYYY-MM-DD; df.index[-1] is day T.
    # We want Nifty close STRICTLY BEFORE T, and the close lookback
    # business days before that.
    decision_date = str(df.index[-1])
    prior_nifty = nifty[nifty.index < decision_date]
    if len(prior_nifty) < lookback + 1:
        return False
    n_t_minus_1 = float(prior_nifty.iloc[-1])
    n_old = float(prior_nifty.iloc[-1 - lookback])
    if n_old <= 0:
        return False
    nifty_ret = n_t_minus_1 / n_old - 1.0

    return stock_ret > nifty_ret


# ---------------------------------------------------------------------------
# E0 — current 6-condition EMA pullback (baseline)
# ---------------------------------------------------------------------------

class E0Generator(SwingSignalGenerator):
    """Baseline. Just an alias so the backtester can name it consistently."""
    name = "E0"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.rejected: Counter = Counter()


# ---------------------------------------------------------------------------
# E1 — E0 + stock-level trend filter
# ---------------------------------------------------------------------------

class E1Generator(E0Generator):
    name = "E1"

    def generate_signal(self, symbol, df, current_weekday=None):
        base = super().generate_signal(symbol, df, current_weekday)
        if base.type != SwingSignalType.BUY:
            return base
        if not _trend_filter_passes(df):
            self.rejected["E1_trend_filter"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                base.reasons + ["[E1 FAIL] stock trend filter (close vs SMA200 / SMA50 vs SMA200)"],
                atr=base.atr, price=base.price, symbol=symbol,
            )
        return base


# ---------------------------------------------------------------------------
# E2 — E1 + relative strength
# ---------------------------------------------------------------------------

class E2Generator(E1Generator):
    name = "E2"
    nifty_series: Optional[pd.Series] = None
    rs_lookback: int = 63

    def generate_signal(self, symbol, df, current_weekday=None):
        base = super().generate_signal(symbol, df, current_weekday)
        if base.type != SwingSignalType.BUY:
            return base
        if not _rs_filter_passes(df, self.nifty_series, self.rs_lookback):
            self.rejected["E2_relative_strength"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                base.reasons + ["[E2 FAIL] 63d RS not above Nifty 50 RS"],
                atr=base.atr, price=base.price, symbol=symbol,
            )
        return base


# ---------------------------------------------------------------------------
# E3 — breakout REPLACING EMA pullback
# ---------------------------------------------------------------------------

@dataclass
class _BreakoutThresholds:
    lookback_days: int = 20
    volume_multiple: float = 1.5
    min_adx: float = 0.0   # not used; here for parity with E0 config shape


class E3Generator:
    """E3: enter on close above the PRIOR 20-day high with volume
    >= 1.5x the 20-day average volume (PRIOR 20-day average — today's
    bar excluded from the average). Same day-of-week gate as the
    baseline so weekly-rhythm parity holds.

    Does NOT inherit from SwingSignalGenerator — the entry mechanism is
    completely different. Matches the SwingSignal return shape so the
    backtester is none the wiser.
    """
    name = "E3"
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self, config: Dict[str, Any]):
        self.lookback = int(config.get("breakout_lookback_days", 20))
        self.vol_mult = float(config.get("breakout_volume_multiple", 1.5))
        self.entry_days: list = config.get("entry_days", [0, 1, 2])
        self.atr_period = int(config.get("atr_period", 14))
        # Minimum bars: lookback + 1 (for prior window) + ATR period.
        self.min_rows = max(self.lookback + 2, self.atr_period + 2)
        self.rejected: Counter = Counter()

    def generate_signal(self, symbol, df, current_weekday=None):
        reasons: list = []
        if df is None or len(df) < self.min_rows:
            return SwingSignal(SwingSignalType.HOLD,
                                [f"insufficient data ({len(df) if df is not None else 0} < {self.min_rows})"],
                                symbol=symbol)

        # Day-of-week gate (parity with baseline).
        if current_weekday is not None and current_weekday not in self.entry_days:
            day = self.DAY_NAMES[current_weekday]
            self.rejected["E3_day_of_week"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                [f"[SKIP] no entries on {day}"],
                symbol=symbol,
            )

        # PRIOR 20-day high (excludes today). high.iloc[-1] is today;
        # we want max of high.iloc[-21:-1].
        prior_window = df.iloc[-self.lookback - 1:-1]
        if len(prior_window) < self.lookback:
            return SwingSignal(SwingSignalType.HOLD, ["insufficient prior window"], symbol=symbol)
        prior_high = float(prior_window["high"].max())
        prior_avg_vol = float(prior_window["volume"].mean())

        today_close = float(df["close"].iloc[-1])
        today_volume = float(df["volume"].iloc[-1])

        # ATR for sizing — uses standard 14-bar window up to and
        # including today, same convention as the baseline.
        atr_series = compute_atr(df["high"], df["low"], df["close"], period=self.atr_period)
        atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0

        # Filter checks
        if today_close <= prior_high:
            self.rejected["E3_no_breakout_close"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                [f"[E3 FAIL] close {today_close:.2f} <= prior {self.lookback}d high {prior_high:.2f}"],
                atr=atr_val, price=today_close, symbol=symbol,
            )
        if prior_avg_vol <= 0:
            self.rejected["E3_zero_vol_window"] += 1
            return SwingSignal(SwingSignalType.HOLD,
                                ["[E3 FAIL] zero prior-window volume"],
                                atr=atr_val, price=today_close, symbol=symbol)
        if today_volume < self.vol_mult * prior_avg_vol:
            self.rejected["E3_volume_below"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                [f"[E3 FAIL] volume {today_volume:.0f} < {self.vol_mult}x avg {prior_avg_vol:.0f}"],
                atr=atr_val, price=today_close, symbol=symbol,
            )

        return SwingSignal(
            type=SwingSignalType.BUY,
            reasons=[f"[E3 OK] breakout close {today_close:.2f} > prior {self.lookback}d high {prior_high:.2f}, "
                      f"volume {today_volume:.0f} >= {self.vol_mult}x avg {prior_avg_vol:.0f}"],
            atr=atr_val, price=today_close, symbol=symbol,
        )


# ---------------------------------------------------------------------------
# E4 — E3 + E1 trend filter
# ---------------------------------------------------------------------------

class E4Generator(E3Generator):
    name = "E4"

    def generate_signal(self, symbol, df, current_weekday=None):
        base = super().generate_signal(symbol, df, current_weekday)
        if base.type != SwingSignalType.BUY:
            return base
        if not _trend_filter_passes(df):
            self.rejected["E4_trend_filter"] += 1
            return SwingSignal(
                SwingSignalType.HOLD,
                base.reasons + ["[E4 FAIL] stock trend filter"],
                atr=base.atr, price=base.price, symbol=symbol,
            )
        return base


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_generator(variant: str, base_config: Dict[str, Any],
                   nifty_series: Optional[pd.Series] = None,
                   ) -> Any:
    """Build the generator instance for ``variant`` (E0 .. E4)."""
    variant = variant.upper()
    if variant == "E0":
        return E0Generator(base_config)
    if variant == "E1":
        return E1Generator(base_config)
    if variant == "E2":
        gen = E2Generator(base_config)
        gen.nifty_series = nifty_series
        return gen
    if variant == "E3":
        return E3Generator(base_config)
    if variant == "E4":
        return E4Generator(base_config)
    raise ValueError(f"unknown entry variant: {variant!r}")
