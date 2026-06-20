"""TDD for build_signal — assemble a typed Signal from a CMCClient.

build_signal is the WP-3 surface WP-2's skill calls to get the live, point-in-time
market snapshot that parameterizes candidate generation. It must read ONLY the
CMCClient's normalized outputs (never raw CMC JSON), and degrade gracefully when a
field is missing. Fully offline (fixtures-backed client)."""
from __future__ import annotations

from datetime import datetime, timezone

from verdict.schema import Signal
from verdict.signals.cmc import CMCClient, build_signal


def _client() -> CMCClient:
    return CMCClient.offline()


def test_build_signal_returns_valid_signal_with_price_and_indicators():
    sig = build_signal("BNB/USDT", _client())
    assert isinstance(sig, Signal)
    assert sig.symbol == "BNB/USDT"
    assert sig.price == 612.34
    # technicals come through with canonical keys
    assert sig.indicators["rsi"] == 58.2
    assert sig.indicators["ema_20"] == 598.10
    assert sig.indicators["atr"] == 18.74


def test_build_signal_fills_market_context_and_regime():
    sig = build_signal("BNB/USDT", _client())
    assert sig.fear_greed == 63.0
    assert sig.btc_dominance == 54.21
    # greed (fng>=60) + BTC uptrend (ema_20 > ema_50) -> risk_on
    assert sig.regime == "risk_on"


def test_build_signal_attaches_per_symbol_derivatives():
    sig = build_signal("BNB/USDT", _client())
    assert sig.funding_rate == 0.00012
    assert sig.open_interest == 742000000.0


def test_build_signal_accepts_explicit_ts_for_determinism():
    ts = datetime(2026, 6, 19, 12, tzinfo=timezone.utc)
    sig = build_signal("BNB/USDT", _client(), ts=ts)
    assert sig.ts == ts


def test_build_signal_source_records_offline_provenance():
    sig = build_signal("BNB/USDT", _client())
    assert sig.source == "cmc-offline"
