"""Regenerate the committed CMC OHLCV fixtures, deterministically and offline.

These candles are SYNTHETIC (a smooth wave + slow drift, no RNG) so the fixtures
are stable across machines and let WP-1/WP-2 backtest without a CMC key. For real
numbers, refresh live via the CMC OHLCV transport or WP-1's CCXT loader.

    python verdict/signals/fixtures/_generate_ohlcv.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOURS_PER_TF = {"1h": 1, "4h": 4}


def _envelope(symbol: str, timeframe: str, n: int, base_price: float, start: datetime) -> dict:
    hours = HOURS_PER_TF[timeframe]
    quotes = []
    for i in range(n):
        t = start + timedelta(hours=hours * i)
        drift = 1.0 + 0.0006 * i              # slow uptrend
        o = base_price * drift * (1 + math.sin(i / 6.0) * 0.02)
        c = base_price * drift * (1 + math.sin((i + 1) / 6.0) * 0.02)
        hi = max(o, c) * 1.006
        lo = min(o, c) * 0.994
        vol = 1_500_000.0 + (i % 12) * 50_000.0
        quotes.append({
            "time_open": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "time_close": (t + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "quote": {"USD": {"open": round(o, 2), "high": round(hi, 2), "low": round(lo, 2),
                              "close": round(c, 2), "volume": vol}},
        })
    return {"status": {"timestamp": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "error_code": 0},
            "data": {"symbol": symbol, "quotes": quotes}}


def main() -> None:
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    for tf, n in (("1h", 120), ("4h", 90)):
        env = _envelope("BNB", tf, n, 600.0, start)
        path = HERE / f"ohlcv_BNB_{tf}.json"
        path.write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.name}: {len(env['data']['quotes'])} bars")


if __name__ == "__main__":
    main()
