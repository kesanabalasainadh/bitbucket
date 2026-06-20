from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from verdict.sentiment.schema import Headline
from verdict.signals.symbols import base_symbol

_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    return _WS.sub(" ", title.strip())


def normalize_headlines(symbol: str, rows: Iterable[dict], *, source: str = "offline") -> list[Headline]:
    base = base_symbol(symbol)
    out: list[Headline] = []
    for row in rows:
        title = normalize_title(str(row.get("title") or row.get("headline") or ""))
        if not title:
            continue
        published = row.get("published_at") or row.get("publishedAt") or row.get("pubDate")
        if isinstance(published, str):
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        elif isinstance(published, datetime):
            published_at = published
        else:
            published_at = datetime.now(timezone.utc)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        out.append(Headline(
            symbol=base,
            title=title,
            source=str(row.get("source") or source),
            url=str(row.get("url") or ""),
            published_at=published_at.astimezone(timezone.utc),
        ))
    return out
