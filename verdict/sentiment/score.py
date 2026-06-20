from __future__ import annotations

from datetime import datetime, timezone
from math import exp

from verdict.sentiment.schema import Headline, SentimentSnapshot
from verdict.signals.symbols import base_symbol

POSITIVE = {
    "adoption", "approval", "bullish", "breakout", "growth", "partnership",
    "rally", "record", "recovery", "surge", "surges", "upgrade", "volume",
    "booming", "boom", "soars", "soar", "jumps", "gains", "inflows",
    "milestone", "outperforms", "expansion", "rebound",
}
NEGATIVE = {
    "attack", "bearish", "crash", "decline", "exploit", "fear", "hack",
    "lawsuit", "liquidation", "outage", "probe", "risk", "risk-off", "selloff", "slump",
    "drop", "drops", "tumble", "tumbles", "plunge", "plunges", "slide", "slides",
    "sinks", "shock", "shocks", "rout", "downturn", "dump", "rejection", "slumps",
}


def _headline_score(title: str) -> float:
    words = {w.strip(".,:;!?()[]{}'\"").lower() for w in title.split()}
    raw = sum(1 for w in words if w in POSITIVE) - sum(1 for w in words if w in NEGATIVE)
    return max(-1.0, min(1.0, raw / 3.0))


def _freshness(now: datetime, headlines: list[Headline]) -> float:
    if not headlines:
        return 0.0
    newest_hours = min(max((now - h.published_at).total_seconds() / 3600.0, 0.0) for h in headlines)
    return round(exp(-newest_hours / 36.0), 4)


def score_headlines(
    symbol: str,
    headlines: list[Headline],
    *,
    now: datetime | None = None,
    provenance: str | None = None,
) -> SentimentSnapshot:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not headlines:
        return SentimentSnapshot(
            symbol=base_symbol(symbol), ts=now, sentiment_score=0.0, confidence=0.0,
            headline_count=0, volatility_adjustment=0.0, freshness=0.0,
            source=provenance or "offline-empty", headlines=[], headline_items=[],
        )

    scores = [_headline_score(h.title) for h in headlines]
    avg = sum(scores) / len(scores)
    score = round(max(-1.0, min(1.0, avg)), 4)
    freshness = _freshness(now, headlines)
    count_conf = min(1.0, len(headlines) / 8.0)
    confidence = round(count_conf * freshness, 4)
    volatility_adjustment = round(min(1.0, abs(score) * confidence), 4)
    # `provenance` (offline | live) is explicit; per-headline `source` is the outlet name.
    source = provenance or ("offline" if all(h.source == "offline" for h in headlines) else "mixed")
    return SentimentSnapshot(
        symbol=base_symbol(symbol),
        ts=now,
        sentiment_score=score,
        confidence=confidence,
        headline_count=len(headlines),
        volatility_adjustment=volatility_adjustment,
        freshness=freshness,
        source=source,
        headlines=[h.title for h in headlines[:8]],
        headline_items=list(headlines[:8]),
    )
