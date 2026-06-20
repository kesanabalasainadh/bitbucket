"""
verdict.core.candidates — deterministic strategy-candidate generation (WP-2).

VERDICT's edge isn't "an LLM guessed a good strategy" — it's "we generate many
*deterministic, inspectable* candidates and let walk-forward validation pick the
honest survivor (or declare none)." This module emits >= 3 distinct archetypes,
each expressed ENTIRELY in verdict.core.rules' grammar so the backtester evaluates
every rule 1:1. No RNG, no LLM, no I/O — given the same (series, signal) it always
returns the same specs.

Archetypes (ported in spirit from the legacy NSE engine, re-pointed to crypto):
  * momentum / trend-pullback   — EMA-stack uptrend + shallow pullback + MACD turn
  * mean-reversion (RSI/Boll)   — fade oversold dislocations below the lower band
  * breakout (Donchian/volume)  — close above prior-N high on a volume surge

Signal parameterization: a live CMC Signal (WP-3) tightens the candidates in
``risk_off`` (stronger trend filter, deeper oversold, higher volume/ADX bars,
smaller risk per trade) and is echoed into each spec's reasoning so a judge can
see exactly how market context shaped the rules.
"""
from __future__ import annotations

from typing import Optional

from verdict.schema import (
    OHLCVSeries, RiskProfile, Signal, StrategyMetrics, StrategySpec,
)


def _slug(symbol: str) -> str:
    return symbol.replace("/", "").replace(":", "").lower()


def _zero_metrics() -> StrategyMetrics:
    return StrategyMetrics(return_pct=0.0, sharpe_ratio=0.0, win_rate=0.0,
                           max_drawdown=0.0, risk_score=0.0)


def _signal_ctx(signal: Optional[Signal]) -> str:
    if signal is None:
        return "No live signal supplied; parameters held at neutral defaults."
    bits = [f"regime={signal.regime or 'neutral'}"]
    if signal.fear_greed is not None:
        bits.append(f"F&G={signal.fear_greed:.0f}")
    if signal.funding_rate is not None:
        bits.append(f"funding={signal.funding_rate:.4%}")
    tail = " — tightened for risk-off." if (signal.regime == "risk_off") else "."
    return "Signal context: " + ", ".join(bits) + tail


# Pre-registered BTC-dominance gate (consumes the CMC global-metrics signal).
# High BTC dominance => capital concentrates in BTC and ALTS bleed; for a NON-BTC
# asset we demand stronger confluence (3-of-3) + tighter risk. For BTC itself,
# high dominance is a tailwind (no penalty). Deterministic; a no-op when the
# signal or btc_dominance is unavailable (offline / partial-data path).
BTC_DOM_HIGH = 55.0    # CMC btc_dominance >= 55% => alt headwind


def _alt_headwind(signal: Optional[Signal], symbol: str) -> bool:
    """True when CMC BTC dominance is high AND the asset is a non-BTC alt."""
    if signal is None or signal.btc_dominance is None:
        return False
    if symbol.split("/")[0].strip().upper() == "BTC":
        return False
    return signal.btc_dominance >= BTC_DOM_HIGH


def generate_candidates(
    series: OHLCVSeries, signal: Optional[Signal] = None
) -> list[StrategySpec]:
    """Return >= 3 deterministic, grammar-expressible StrategySpec candidates."""
    symbol, tf = series.symbol, series.timeframe
    regime = (signal.regime if signal else None) or "neutral"
    risk_off = regime == "risk_off"
    risk_profile = RiskProfile.CONSERVATIVE if risk_off else RiskProfile.BALANCED
    size = "risk 1% of equity per trade" if risk_off else "risk 2% of equity per trade"
    risk_limits = {"max_drawdown_pct": 25, "max_position_pct": 20}
    data_source = (f"cmc ({signal.source}) + {series.source}" if signal else series.source)
    ctx = _signal_ctx(signal)
    slug = _slug(symbol)

    # CMC BTC-DOMINANCE GATE — consumes signal.btc_dominance. High dominance =>
    # alts bleed; for a non-BTC asset tighten risk (conservative profile + halved
    # size) and require 3-of-3 confluence instead of 2-of-3. No-op for BTC and on
    # the offline/None path, so behaviour degrades gracefully.
    alt_headwind = _alt_headwind(signal, symbol)
    confluence_n = 2
    if alt_headwind:
        risk_profile = RiskProfile.CONSERVATIVE
        size = "risk 1% of equity per trade"
        confluence_n = 3
        ctx = ctx + (f" BTC dominance {signal.btc_dominance:.1f}% >= {BTC_DOM_HIGH:.0f}% "
                     f"(alt headwind): tightened risk + 3-of-3 confluence for {symbol}.")

    def spec(**kw) -> StrategySpec:
        base = dict(
            assets=[symbol], timeframe=tf, risk_profile=risk_profile,
            position_size=size, risk_limits=dict(risk_limits),
            metrics=_zero_metrics(), market_regime=regime,
            data_source=data_source, confidence=0.0,
        )
        base.update(kw)
        return StrategySpec(**base)

    # 1) Momentum / trend-following ---------------------------------------- #
    # Ride a confirmed bullish EMA stack while momentum is positive; exit when the
    # short-term trend breaks. NO upper RSI cap — in a real uptrend RSI sits well
    # above 65, so capping it (the old "rsi in [40,65]") made the archetype unable
    # to enter a trend at all. Strength is the signal here, not a fade.
    mom_entry = [
        # REGIME GATE — eligible only in a confirmed uptrend (ADX strength + bullish
        # EMA stack + positive slope). A pro doesn't trade momentum in chop.
        f"adx_14 >= {28 if risk_off else 25}",
        "ema_20 > ema_50",
        "ema_50 > ema_100",
        f"ema_slope_50 > {0.004 if risk_off else 0.002}",
        # CONFLUENCE — 2-of-3: momentum thrust, RSI above midline, higher-TF alignment.
        f"at_least {confluence_n} of [macd_hist > 0; rsi_14 > {55 if risk_off else 50}; ema_100 > ema_200]",
    ]
    momentum = spec(
        id=f"momentum-{slug}-{tf}",
        name=f"{symbol} {tf} Trend Momentum",
        description="Eligible only in a confirmed uptrend (ADX + bullish EMA stack + "
                    "positive slope); enter on 2-of-3 confluence and ride until the 20/50 "
                    "stack breaks. ATR risk bracket.",
        horizon="trend-follow (10-40 bars)", lookback=210 if risk_off else 120,
        indicators=["EMA(20)", "EMA(50)", "EMA(100)", "EMA(200)", "EMA_slope(50)",
                    "ADX(14)", "MACD(12,26,9)", "RSI(14)", "ATR(14)"],
        entry_rules=mom_entry,
        exit_rules=["ema_20 crosses_below ema_50", "max_hold=40 bars"],
        stop_loss="2.0 * ATR(14)", take_profit="8.0 * ATR(14)",
        reasoning="Trend momentum (regime-gated): only fires when ADX confirms a trend and "
                  "the EMA stack is bullish with positive slope; needs 2-of-3 of {MACD>0, "
                  "RSI>mid, EMA100>EMA200}, then rides until the 20/50 stack rolls over. " + ctx,
    )

    # 2) Mean-reversion (regime-gated, confirmed-turn) --------------------- #
    # THE knife-catch fix. Mean-reversion is eligible ONLY in a RANGE (low ADX) —
    # most losing reversion trades are downtrend dead-cat bounces, and the regime
    # gate deletes them outright. We then require a CONFIRMED turn (2-of-3) rather
    # than buying oversold, and lean on the range floor (donchian_low) for a tight
    # structural invalidation. Exit back at the band mean.
    turn_floor = 30 if risk_off else 35
    meanrev = spec(
        id=f"meanrev-{slug}-{tf}",
        name=f"{symbol} {tf} Mean-Reversion (range, confirmed turn)",
        description="Eligible only in a low-ADX range; buy a CONFIRMED reversion turn off "
                    "the range floor (2-of-3 confluence), exit at the band mean.",
        horizon="swing (2-12 bars)", lookback=120,
        indicators=["BollingerBands(20,2)", "RSI(14)", "ADX(14)",
                    "Donchian(20)", "ATR(14)"],
        entry_rules=[
            # REGIME GATE — range only (kills downtrend knife-catches)
            f"adx_14 < {18 if risk_off else 22}",
            "close > donchian_low_20",          # reclaimed the range floor, not mid-fall
            "close < bb_mid",                   # below the mean — genuine dislocation
            # CONFIRMED TURN — 2-of-3: the reversal is in, not hoped-for
            f"at_least 2 of [rsi_14 crosses_above {turn_floor}; close > open; macd_hist rising]",
        ],
        exit_rules=["close crosses_above bb_mid", "rsi_14 > 60", "max_hold=12 bars",
                    "close crosses_below donchian_low_20"],   # structural invalidation
        stop_loss="1.5 * ATR(14)", take_profit="2.0 * ATR(14)",
        reasoning="Mean-reversion (regime-gated): only in a low-ADX range, buy a confirmed "
                  "turn (2-of-3 of {RSI reclaim, up-close, MACD rising}) that has reclaimed "
                  "the range floor; exit at the band mean. No knife-catching in trends. " + ctx,
    )

    # 3) Breakout (Donchian / volume) -------------------------------------- #
    vol_mult = 2.0 if risk_off else 1.5
    adx_min = 25 if risk_off else 20
    breakout = spec(
        id=f"breakout-{slug}-{tf}",
        name=f"{symbol} {tf} Donchian Breakout",
        description="Enter on a close above the prior-20-bar high confirmed by a volume "
                    "surge in a trending tape (ADX); wide ATR target.",
        horizon="swing (4-12 bars)", lookback=120,
        indicators=["Donchian(20)", "VolumeSMA(20)", "ADX(14)", "ATR(14)"],
        entry_rules=[
            "close > donchian_high_20",
            f"volume > vol_sma_20 * {vol_mult}",
            f"adx_14 > {adx_min}",
            # CONFLUENCE — 2-of-3: above mid-trend, RSI thrust, EMA stack alignment.
            f"at_least {confluence_n} of [close > ema_50; rsi_14 > 55; ema_50 > ema_100]",
        ],
        exit_rules=["max_hold=12 bars", "ema_20 crosses_below ema_50"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        reasoning="Breakout: ride volatility expansion when price clears the prior-20-bar "
                  "high on above-average volume with ADX confirming a trend, plus 2-of-3 "
                  "confluence (mid-trend, RSI thrust, stack alignment). " + ctx,
    )

    return [momentum, meanrev, breakout]
