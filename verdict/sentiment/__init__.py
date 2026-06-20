"""Sentiment layer for bounded, cacheable market context."""

from verdict.sentiment.schema import Headline, SentimentSnapshot
from verdict.sentiment.signals import build_sentiment_snapshot

__all__ = ["Headline", "SentimentSnapshot", "build_sentiment_snapshot"]
