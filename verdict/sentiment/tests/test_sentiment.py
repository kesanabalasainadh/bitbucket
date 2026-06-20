from __future__ import annotations

from datetime import datetime, timezone

from verdict.sentiment.signals import build_sentiment_snapshot


def test_sentiment_snapshot_is_bounded_and_deterministic():
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    headlines = [
        {"title": "BNB adoption surge after ecosystem upgrade", "published_at": now.isoformat()},
        {"title": "Crypto market risk rises after liquidation wave", "published_at": now.isoformat()},
    ]
    a = build_sentiment_snapshot("BNB/USDT", headlines=headlines, now=now, use_cache=False)
    b = build_sentiment_snapshot("BNB/USDT", headlines=headlines, now=now, use_cache=False)
    assert a.model_dump() == b.model_dump()
    assert -1.0 <= a.sentiment_score <= 1.0
    assert 0.0 <= a.confidence <= 1.0
    assert a.headline_count == 2


def test_offline_fallback_produces_cacheable_snapshot(tmp_path):
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    snap = build_sentiment_snapshot("CAKE/USDT", now=now, cache_dir=tmp_path)
    cached = build_sentiment_snapshot("CAKE/USDT", now=now, cache_dir=tmp_path)
    assert snap == cached
    assert snap.headline_count >= 1
    assert snap.source == "offline"
