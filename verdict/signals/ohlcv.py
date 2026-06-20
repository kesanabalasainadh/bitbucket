"""
verdict.signals.ohlcv — parse CMC ``ohlcv/historical`` JSON into an OHLCVSeries.

This is the candle surface WP-1's ``load_ohlcv(source='cmc')`` consumes. CMC
historical depth depends on plan tier; for deep intraday backtests WP-1 falls back
to CCXT (see ``verdict/core/data.py``) and tags ``source`` accordingly. Here we
only normalize whatever CMC returns into the shared schema — tz-aware UTC, sorted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from verdict.schema import OHLCVBar, OHLCVSeries


def _as_utc(ts_raw: Any) -> datetime:
    """Parse an ISO-8601 timestamp (CMC uses a trailing 'Z') to tz-aware UTC."""
    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_ohlcv(
    envelope: dict, symbol: str, timeframe: str, *, source: str = "cmc"
) -> OHLCVSeries:
    """CMC OHLCV envelope -> OHLCVSeries(symbol, timeframe), bars sorted ascending.

    Tolerant of the nested ``quote.USD`` shape and a flat fallback, and of the two
    common timestamp keys (``time_open`` / ``timestamp``).
    """
    data = envelope.get("data", envelope) or {}
    quotes = data.get("quotes") or data.get("ohlcv") or []

    bars: list[OHLCVBar] = []
    for q in quotes:
        usd = (q.get("quote") or {}).get("USD") or q  # nested or flat
        ts_raw = (
            q.get("time_open")
            or q.get("timestamp")
            or q.get("time")
            or usd.get("time_open")
        )
        bars.append(
            OHLCVBar(
                ts=_as_utc(ts_raw),
                open=float(usd["open"]),
                high=float(usd["high"]),
                low=float(usd["low"]),
                close=float(usd["close"]),
                volume=float(usd.get("volume", 0.0)),
            )
        )
    bars.sort(key=lambda b: b.ts)
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, source=source, bars=bars)
