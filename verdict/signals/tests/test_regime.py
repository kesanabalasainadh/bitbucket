"""TDD for the market-regime rule — risk_on / risk_off / neutral.

The rule is pre-registered (committed before seeing live data) so judges can audit
it: a blend of CMC Fear&Greed and the BTC trend. Conflicting signals cancel to
neutral. Pure function, fully offline.
"""
from __future__ import annotations

from verdict.signals.normalize import derive_regime


def test_greed_and_uptrend_is_risk_on():
    assert derive_regime(fear_greed=72, btc_trend_up=True) == "risk_on"


def test_fear_and_downtrend_is_risk_off():
    assert derive_regime(fear_greed=18, btc_trend_up=False) == "risk_off"


def test_greed_but_downtrend_cancels_to_neutral():
    assert derive_regime(fear_greed=75, btc_trend_up=False) == "neutral"


def test_fear_but_uptrend_cancels_to_neutral():
    assert derive_regime(fear_greed=20, btc_trend_up=True) == "neutral"


def test_neutral_fng_follows_uptrend():
    # 40 < fng < 60 contributes nothing; the BTC trend breaks the tie.
    assert derive_regime(fear_greed=50, btc_trend_up=True) == "risk_on"


def test_neutral_fng_follows_downtrend():
    assert derive_regime(fear_greed=50, btc_trend_up=False) == "risk_off"


def test_greed_alone_with_unknown_trend_is_risk_on():
    assert derive_regime(fear_greed=80, btc_trend_up=None) == "risk_on"


def test_no_data_is_neutral():
    assert derive_regime(fear_greed=None, btc_trend_up=None) == "neutral"
