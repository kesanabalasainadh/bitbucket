"""TDD for verdict.core.data — the candle loader (offline-first, reproducible)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from verdict.schema import OHLCVBar, OHLCVSeries
from verdict.core import data as data_mod


def _series(symbol="BNB/USDT", timeframe="4h"):
    bars = [
        OHLCVBar(
            ts=datetime(2024, 1, 1, h, tzinfo=timezone.utc),
            open=100 + h, high=101 + h, low=99 + h, close=100.5 + h, volume=1000 + h,
        )
        for h in range(0, 12, 4)  # three 4h bars: 00:00, 04:00, 08:00
    ]
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, source="ccxt-kucoin", bars=bars)


def test_fixture_roundtrip_preserves_bars(tmp_path):
    """Writing a series to a csv.gz fixture and reading it back is lossless."""
    s = _series()
    path = tmp_path / "BNB-USDT_4h.csv.gz"
    data_mod._write_candles(s, path)
    assert path.exists()

    back = data_mod._read_candles("BNB/USDT", "4h", path)
    assert isinstance(back, OHLCVSeries)
    assert back.symbol == "BNB/USDT"
    assert back.timeframe == "4h"
    assert len(back.bars) == 3
    for a, b in zip(s.bars, back.bars):
        assert a.ts == b.ts
        assert a.ts.tzinfo is not None  # tz-aware UTC preserved
        assert (a.open, a.high, a.low, a.close, a.volume) == (
            b.open, b.high, b.low, b.close, b.volume
        )


def test_load_ohlcv_reads_fixture_and_slices_range(tmp_path):
    """load_ohlcv defaults to the committed fixture and respects [start, end]."""
    s = _series()
    data_mod._write_candles(s, tmp_path / "BNB-USDT_4h.csv.gz")

    out = data_mod.load_ohlcv(
        "BNB/USDT", "4h",
        start=datetime(2024, 1, 1, 4, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 8, tzinfo=timezone.utc),
        fixture_dir=tmp_path,
    )
    assert [b.ts.hour for b in out.bars] == [4, 8]  # 00:00 sliced off
    # sorted ascending
    assert out.bars == sorted(out.bars, key=lambda b: b.ts)


def test_load_ohlcv_is_offline_by_default(tmp_path):
    """With a fixture present, the loader must NEVER hit the network."""
    s = _series()
    data_mod._write_candles(s, tmp_path / "BNB-USDT_4h.csv.gz")

    def explode(*a, **k):
        raise AssertionError("network fetch must not be called when a fixture exists")

    out = data_mod.load_ohlcv("BNB/USDT", "4h", fixture_dir=tmp_path, fetcher=explode)
    assert len(out.bars) == 3


def test_load_ohlcv_refresh_uses_fetcher_and_writes_fixture(tmp_path):
    """source='ccxt' with refresh=True calls the injected fetcher and caches the result."""
    captured = {}

    def fake_fetcher(symbol, timeframe, start, end):
        captured["called"] = (symbol, timeframe)
        return _series(symbol, timeframe)

    out = data_mod.load_ohlcv(
        "BNB/USDT", "4h", source="ccxt", refresh=True,
        fixture_dir=tmp_path, fetcher=fake_fetcher,
    )
    assert captured["called"] == ("BNB/USDT", "4h")
    assert len(out.bars) == 3
    # fixture was written so a subsequent offline load works
    again = data_mod.load_ohlcv("BNB/USDT", "4h", fixture_dir=tmp_path)
    assert len(again.bars) == 3


def test_load_ohlcv_missing_fixture_no_fetcher_raises(tmp_path):
    """No fixture and no fetch path is a clear, loud error (never silent-empty)."""
    with pytest.raises(FileNotFoundError):
        data_mod.load_ohlcv("DOGE/USDT", "1h", fixture_dir=tmp_path)
