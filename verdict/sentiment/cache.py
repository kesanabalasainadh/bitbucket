from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from verdict.sentiment.schema import SentimentSnapshot
from verdict.signals.symbols import base_symbol

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "sentiment"


def cache_path(symbol: str, cache_dir: Path = CACHE_DIR) -> Path:
    return Path(cache_dir) / f"{base_symbol(symbol)}.json"


def read_cached(symbol: str, *, max_age_minutes: int = 60, cache_dir: Path = CACHE_DIR) -> Optional[SentimentSnapshot]:
    path = cache_path(symbol, cache_dir)
    if not path.exists():
        return None
    snap = SentimentSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    age = datetime.now(timezone.utc) - snap.ts
    if age > timedelta(minutes=max_age_minutes):
        return None
    return snap


def write_cached(snapshot: SentimentSnapshot, *, cache_dir: Path = CACHE_DIR) -> Path:
    path = cache_path(snapshot.symbol, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return path
