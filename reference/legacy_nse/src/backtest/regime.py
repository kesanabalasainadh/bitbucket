"""
Regime classifier (Phase 4 / addendum §B).

Two regimes computed independently and both consulted at each daily scan:

  * **VIX regime** — three-band classification on India VIX close of
    day T-1 (no same-bar leak; identical contract to Phase 1 audit
    item C4):
        NORMAL    : VIX < 17                  → full size, all groups.
        ELEVATED  : 17 <= VIX < 22            → size × 0.5,
                                                NO new entries in
                                                ``high_beta_cyclicals``.
        CRISIS    : VIX >= 22                 → NO new entries at all,
                                                existing positions keep
                                                their stops (we do not
                                                panic-exit on regime).

  * **Market trend** — 50-day vs 200-day SMA of Nifty 50 close of
    day T-1.
        UP        : SMA50 > SMA200             → strategy thresholds
                                                 unchanged.
        DOWN      : SMA50 < SMA200             → require strategy
                                                 signal threshold to
                                                 clear ``downtrend_signal_multiplier``
                                                 × baseline (default 1.5).

Thresholds are exposed via ``RegimeConfig`` so live + backtest run
identical code. The classifier never reads same-bar data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class VixRegime(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRISIS = "CRISIS"


class MarketTrend(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"   # not enough data for 200-day SMA yet


@dataclass(frozen=True)
class RegimeConfig:
    vix_elevated_threshold: float = 17.0
    vix_crisis_threshold: float = 22.0
    elevated_size_multiplier: float = 0.5
    elevated_blocked_groups: tuple = ("high_beta_cyclicals",)
    sma_fast_days: int = 50
    sma_slow_days: int = 200
    downtrend_signal_multiplier: float = 1.5
    # Whether the gate is active. Setting this False is how the
    # walk-forward "comparison without the regime filter" runs.
    enabled: bool = True


@dataclass(frozen=True)
class RegimeDecision:
    """Result of classifying day T's regime using T-1 data only."""
    vix: VixRegime
    trend: MarketTrend
    vix_value: Optional[float]
    nifty_close: Optional[float]
    sma_fast: Optional[float]
    sma_slow: Optional[float]
    # Effective controls:
    size_multiplier: float
    blocked_groups: tuple
    threshold_multiplier: float
    block_all_entries: bool

    def reason(self) -> str:
        vix_str = f"{self.vix_value:.2f}" if self.vix_value is not None else "?"
        trend_str = "?"
        if self.sma_fast is not None and self.sma_slow is not None:
            trend_str = f"50d={self.sma_fast:.0f} vs 200d={self.sma_slow:.0f}"
        return (
            f"VIX={self.vix.value}({vix_str}) "
            f"TREND={self.trend.value}({trend_str}) "
            f"size×{self.size_multiplier:.2f} "
            f"thresh×{self.threshold_multiplier:.2f}"
            + (f" blocked={list(self.blocked_groups)}" if self.blocked_groups else "")
        )


def _classify_vix(value: Optional[float], cfg: RegimeConfig) -> VixRegime:
    if value is None:
        return VixRegime.NORMAL   # fail open: don't block when VIX unknown
    if value >= cfg.vix_crisis_threshold:
        return VixRegime.CRISIS
    if value >= cfg.vix_elevated_threshold:
        return VixRegime.ELEVATED
    return VixRegime.NORMAL


def _classify_trend(
    fast: Optional[float], slow: Optional[float],
) -> MarketTrend:
    if fast is None or slow is None:
        return MarketTrend.UNKNOWN
    return MarketTrend.UP if fast > slow else MarketTrend.DOWN


def _prior_value(series: Optional[pd.Series], date: str) -> Optional[float]:
    """Most recent series value STRICTLY before ``date`` (YYYY-MM-DD).
    Mirrors swing_backtester._vix_blocks_entry's pre-decision contract.
    """
    if series is None or series.empty:
        return None
    prior = series[series.index < date]
    if prior.empty:
        return None
    val = prior.iloc[-1]
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def classify_regime(
    date: str,
    vix_series: Optional[pd.Series] = None,
    nifty_series: Optional[pd.Series] = None,
    cfg: RegimeConfig = RegimeConfig(),
) -> RegimeDecision:
    """Return the regime for ``date`` (YYYY-MM-DD) using T-1 data.

    When ``cfg.enabled`` is False, returns a no-op decision: full size,
    no group blocks, no entry block, no threshold inflation. This is
    the "regime off" arm of the walk-forward comparison.
    """
    vix_value = _prior_value(vix_series, date)
    nifty_close = _prior_value(nifty_series, date)
    sma_fast: Optional[float] = None
    sma_slow: Optional[float] = None
    if nifty_series is not None and not nifty_series.empty:
        prior_nifty = nifty_series[nifty_series.index < date]
        if len(prior_nifty) >= cfg.sma_slow_days:
            sma_fast = float(prior_nifty.tail(cfg.sma_fast_days).mean())
            sma_slow = float(prior_nifty.tail(cfg.sma_slow_days).mean())

    vix = _classify_vix(vix_value, cfg)
    trend = _classify_trend(sma_fast, sma_slow)

    if not cfg.enabled:
        return RegimeDecision(
            vix=vix, trend=trend,
            vix_value=vix_value, nifty_close=nifty_close,
            sma_fast=sma_fast, sma_slow=sma_slow,
            size_multiplier=1.0,
            blocked_groups=(),
            threshold_multiplier=1.0,
            block_all_entries=False,
        )

    size_mult = 1.0
    blocked: tuple = ()
    block_all = False
    if vix == VixRegime.ELEVATED:
        size_mult = cfg.elevated_size_multiplier
        blocked = cfg.elevated_blocked_groups
    elif vix == VixRegime.CRISIS:
        block_all = True

    thresh_mult = cfg.downtrend_signal_multiplier if trend == MarketTrend.DOWN else 1.0

    return RegimeDecision(
        vix=vix, trend=trend,
        vix_value=vix_value, nifty_close=nifty_close,
        sma_fast=sma_fast, sma_slow=sma_slow,
        size_multiplier=size_mult,
        blocked_groups=blocked,
        threshold_multiplier=thresh_mult,
        block_all_entries=block_all,
    )
