"""TDD for CMCClient over the committed offline fixtures — the path WP-1/WP-2
integrate against today (no CMC key). Every method must return typed/normalized
data; the raw CMC envelope must never leak out. Fully offline."""
from __future__ import annotations

import pytest

from verdict.schema import OHLCVSeries
from verdict.signals.cmc import CMCClient


def client() -> CMCClient:
    return CMCClient.offline()


def test_quotes_returns_symbol_to_price_floats():
    q = client().quotes(["BNB/USDT", "BTC/USDT"])
    assert q["BNB/USDT"] == 612.34
    assert q["BTC/USDT"] == 104230.5
    assert all(isinstance(v, float) for v in q.values())


def test_technicals_returns_canonical_indicator_keys():
    t = client().technicals("BNB/USDT")
    expected = {"rsi", "macd", "macd_signal", "ema_20", "ema_50", "ema_100", "atr", "adx"}
    assert expected.issubset(t)
    assert t["rsi"] == 58.2          # fixture stores rsi_14 -> normalized to rsi
    assert t["ema_20"] == 598.10
    assert all(isinstance(v, float) for v in t.values())


def test_global_metrics_has_fear_greed_and_btc_dominance():
    g = client().global_metrics()
    assert g["fear_greed"] == 63.0   # fixture nests under fear_and_greed.value
    assert g["btc_dominance"] == 54.21


def test_derivatives_has_funding_and_open_interest_by_symbol():
    d = client().derivatives()
    assert d["funding_rate"]["BNB"] == 0.00012
    assert d["open_interest"]["BNB"] == 742000000.0


def test_ohlcv_returns_typed_series_from_fixture():
    s = client().ohlcv("BNB/USDT", "1h")
    assert isinstance(s, OHLCVSeries)
    assert s.symbol == "BNB/USDT" and s.timeframe == "1h"
    assert len(s.bars) >= 50
    assert s.bars == sorted(s.bars, key=lambda b: b.ts)


def test_offline_missing_fixture_raises_loudly():
    with pytest.raises(FileNotFoundError):
        client().ohlcv("DOGE/USDT", "1h")


def test_no_raw_envelope_leaks_quotes_are_plain_floats():
    q = client().quotes(["BNB/USDT"])
    assert isinstance(q["BNB/USDT"], float)  # a price, not a nested CMC quote dict
