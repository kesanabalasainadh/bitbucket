from __future__ import annotations

from datetime import datetime, timedelta, timezone

from verdict.sentiment.normalize import normalize_headlines
from verdict.sentiment.schema import Headline
from verdict.signals.symbols import base_symbol


def offline_headlines(symbol: str, *, now: datetime | None = None) -> list[Headline]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = base_symbol(symbol)
    rows = [
        {"title": f"{base} market volume steadies as traders wait for confirmation", "published_at": now - timedelta(hours=4)},
        {"title": "Crypto market risk remains mixed after recent liquidation wave", "published_at": now - timedelta(hours=10)},
        {"title": f"{base} ecosystem upgrade narrative supports cautious adoption", "published_at": now - timedelta(hours=18)},
    ]
    return normalize_headlines(symbol, rows)
