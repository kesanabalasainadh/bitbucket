"""TDD for CMC OHLCV parsing -> OHLCVSeries (the candles WP-1 consumes via
load_ohlcv(source='cmc')). Must be tz-aware UTC, sorted, and tolerant of the
nested quote.USD envelope CMC returns. Pure function, fully offline."""
from __future__ import annotations

from verdict.schema import OHLCVSeries
from verdict.signals.ohlcv import parse_ohlcv

# A minimal cryptocurrency/ohlcv/historical envelope, bars deliberately unsorted.
ENV = {
    "status": {"error_code": 0},
    "data": {
        "symbol": "BNB",
        "quotes": [
            {"time_open": "2026-06-01T08:00:00.000Z",
             "quote": {"USD": {"open": 600.0, "high": 610.0, "low": 595.0,
                               "close": 605.0, "volume": 1.0e9}}},
            {"time_open": "2026-06-01T04:00:00.000Z",
             "quote": {"USD": {"open": 590.0, "high": 602.0, "low": 588.0,
                               "close": 600.0, "volume": 9.0e8}}},
        ],
    },
}


def test_parse_ohlcv_returns_typed_series():
    s = parse_ohlcv(ENV, "BNB/USDT", "4h")
    assert isinstance(s, OHLCVSeries)
    assert s.symbol == "BNB/USDT"
    assert s.timeframe == "4h"
    assert s.source == "cmc"
    assert len(s.bars) == 2


def test_parse_ohlcv_sorts_ascending_and_is_tz_aware_utc():
    s = parse_ohlcv(ENV, "BNB/USDT", "4h")
    assert [b.ts.hour for b in s.bars] == [4, 8]
    for b in s.bars:
        assert b.ts.tzinfo is not None
        assert b.ts.utcoffset().total_seconds() == 0


def test_parse_ohlcv_maps_ohlcv_fields():
    s = parse_ohlcv(ENV, "BNB/USDT", "4h")
    first = s.bars[0]  # the 04:00 bar after sorting
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        590.0, 602.0, 588.0, 600.0, 9.0e8
    )


def test_parse_ohlcv_empty_quotes_is_empty_series():
    s = parse_ohlcv({"data": {"quotes": []}}, "BNB/USDT", "1h")
    assert isinstance(s, OHLCVSeries)
    assert s.bars == []
