from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verdict.sentiment.normalize import normalize_headlines
from verdict.sentiment.schema import Headline
from verdict.signals.symbols import base_symbol

# Committed real-news snapshot: real headlines + sources + working URLs, captured
# on `as_of`. Keeps the demo honest (clickable real sources) AND reproducible
# (no key, no network). See verdict/sentiment/_fixtures/headlines.json.
_FIXTURE = Path(__file__).parent / "_fixtures" / "headlines.json"


def _committed_rows() -> list[dict]:
    try:
        data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in (data.get("headlines") or []) if r.get("title")]


def offline_headlines(symbol: str, *, now: datetime | None = None) -> list[Headline]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = base_symbol(symbol)
    rows = _committed_rows()
    if rows:
        # Real committed snapshot (title + source + url + real publish date).
        return normalize_headlines(symbol, rows)
    # Fallback only if the fixture is missing: synthetic samples (no real URLs).
    rows = [
        {"title": f"{base} market volume steadies as traders wait for confirmation", "published_at": now - timedelta(hours=4)},
        {"title": "Crypto market risk remains mixed after recent liquidation wave", "published_at": now - timedelta(hours=10)},
        {"title": f"{base} ecosystem upgrade narrative supports cautious adoption", "published_at": now - timedelta(hours=18)},
    ]
    return normalize_headlines(symbol, rows)
