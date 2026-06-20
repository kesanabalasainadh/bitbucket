"""
verdict.signals.normalize — turn a CMCClient's normalized fields into a Signal.

Pure mapping + a documented, pre-registered market-regime rule. No network or
provider JSON here: every value arrives via the injected CMCClient (which may be
backed by live MCP/REST or by offline fixtures). Strategy code reads the Signal;
it must never reach back into raw CMC JSON.
"""
from __future__ import annotations

from typing import Optional

# Pre-registered regime thresholds (documented so judges can audit the rule).
GREED_FNG = 60.0   # CMC Fear & Greed >= 60 => "greed"  (risk-seeking)
FEAR_FNG = 40.0    # CMC Fear & Greed <= 40 => "fear"   (risk-averse)


def derive_regime(fear_greed: Optional[float], btc_trend_up: Optional[bool]) -> str:
    """Map Fear&Greed + BTC trend onto ``risk_on`` / ``risk_off`` / ``neutral``.

    Pre-registered rule (committed before seeing live data):

        score = fng_vote + trend_vote, where
          fng_vote   = +1 if fear_greed >= 60, -1 if <= 40, else 0
          trend_vote = +1 if BTC trend up, -1 if BTC trend down, else 0

        score >= +1 -> "risk_on";  score <= -1 -> "risk_off";  else "neutral".

    Conflicting signals (e.g. greed + downtrend) cancel to ``neutral`` — we only
    claim a regime when sentiment and price agree, or one side is decisive and the
    other is silent.
    """
    score = 0
    if fear_greed is not None:
        if fear_greed >= GREED_FNG:
            score += 1
        elif fear_greed <= FEAR_FNG:
            score -= 1
    if btc_trend_up is True:
        score += 1
    elif btc_trend_up is False:
        score -= 1

    if score >= 1:
        return "risk_on"
    if score <= -1:
        return "risk_off"
    return "neutral"
