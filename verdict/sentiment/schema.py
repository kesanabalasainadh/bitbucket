from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Headline(BaseModel):
    symbol: str
    title: str
    source: str = "offline"
    url: str = ""
    published_at: datetime


class SentimentSnapshot(BaseModel):
    symbol: str
    ts: datetime
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    headline_count: int = Field(ge=0)
    volatility_adjustment: float = Field(ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    source: str = "offline"
    headlines: list[str] = Field(default_factory=list)
    # Structured headlines (title + outlet + url) for UIs that link sources.
    # Kept alongside `headlines` (titles-only) for backward compatibility.
    headline_items: list[Headline] = Field(default_factory=list)
