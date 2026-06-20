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

    def spec(**kw) -> StrategySpec:
        base = dict(
            assets=[symbol], timeframe=tf, risk_profile=risk_profile,
            position_size=size, risk_limits=dict(risk_limits),
            metrics=_zero_metrics(), market_regime=regime,
            data_source=data_source, confidence=0.0,
        )
        base.update(kw)
        return StrategySpec(**base)

    # 1) Momentum / trend-pullback ----------------------------------------- #
    trend_anchor = "ema_200" if risk_off else "ema_100"
    momentum = spec(
        id=f"momentum-{slug}-{tf}",
        name=f"{symbol} {tf} Momentum Pullback",
        description="EMA-stack uptrend + shallow pullback into EMA20, MACD momentum "
                    "resuming, RSI healthy; ATR risk bracket.",
        horizon="swing (3-10 bars)", lookback=210 if risk_off else 120,
        indicators=["EMA(20)", "EMA(50)", f"EMA({200 if risk_off else 100})",
                    "MACD(12,26,9)", "RSI(14)", "ATR(14)"],
        entry_rules=[
            f"close > {trend_anchor}",
            "ema_20 > ema_50",
            "abs(close-ema_20)/ema_20 <= 0.04",
            "macd_hist rising",
            "rsi_14 in [40,65]",
        ],
        exit_rules=["rsi_14 > 78", "max_hold=10 bars"],
        stop_loss="1.5 * ATR(14)", take_profit="3.0 * ATR(14)",
        reasoning="Trend-pullback: buy shallow dips inside a confirmed uptrend "
                  "(EMA stack) when MACD histogram turns back up. " + ctx,
    )

    # 2) Mean-reversion (RSI / Bollinger) ---------------------------------- #
    rsi_floor = 30 if risk_off else 35
    meanrev = spec(
        id=f"meanrev-{slug}-{tf}",
        name=f"{symbol} {tf} Mean-Reversion (RSI/Bollinger)",
        description="Fade capitulation below the lower Bollinger band while above the "
                    "long-term trend; exit on reversion to the mean.",
        horizon="swing (2-8 bars)", lookback=210,
        indicators=["BollingerBands(20,2)", "RSI(14)", "EMA(200)", "ATR(14)"],
        entry_rules=[
            "close < bb_lower",
            f"rsi_14 < {rsi_floor}",
            "close > ema_200",
        ],
        exit_rules=["rsi_14 > 55", "max_hold=8 bars"],
        stop_loss="1.5 * ATR(14)", take_profit="2.5 * ATR(14)",
        reasoning="Mean-reversion: buy oversold dislocations (below lower band + low "
                  "RSI) but only with the long-term trend (above EMA200); take profit "
                  "as price reverts toward the mean. " + ctx,
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
        ],
        exit_rules=["max_hold=12 bars"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        reasoning="Breakout: ride volatility expansion when price clears the prior-20-"
                  "bar high on above-average volume with ADX confirming a trend. " + ctx,
    )

    return [momentum, meanrev, breakout]
