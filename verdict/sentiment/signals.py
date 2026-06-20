from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from verdict.sentiment.cache import read_cached, write_cached
from verdict.sentiment.news import offline_headlines
from verdict.sentiment.normalize import normalize_headlines
from verdict.sentiment.schema import Headline, SentimentSnapshot
from verdict.sentiment.score import score_headlines


def build_sentiment_snapshot(
    symbol: str,
    *,
    headlines: Iterable[dict] | list[Headline] | None = None,
    now: datetime | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> SentimentSnapshot:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if use_cache and cache_dir is not None:
        cached = read_cached(symbol, cache_dir=cache_dir)
        if cached is not None:
            return cached

    if headlines is None:
        items = offline_headlines(symbol, now=now)
    else:
        raw = list(headlines)
        if raw and isinstance(raw[0], Headline):
            items = raw  # type: ignore[assignment]
        else:
            items = normalize_headlines(symbol, raw)

    snapshot = score_headlines(symbol, list(items), now=now)
    if use_cache and cache_dir is not None:
        write_cached(snapshot, cache_dir=cache_dir)
    return snapshot
