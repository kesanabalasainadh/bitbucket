from typing import List, Dict, Any
from verdict.schema import NewsEvent

def compute_features(events: List[NewsEvent]) -> Dict[str, float]:
    """Compute sentiment features from raw news events."""
    if not events:
        return {
            "sentiment_score": 0.0,
            "velocity": 0.0,
            "shock": 0.0,
            "source_agreement": 0.0,
            "freshness": 0.0,
            "news_volume": 0.0
        }
    
    # Simple deterministic feature logic for simulation
    score = 0.0
    for e in events:
        if e.sentiment_raw == "positive":
            score += e.confidence
        elif e.sentiment_raw == "negative":
            score -= e.confidence
            
    avg_score = score / len(events)
    
    return {
        "sentiment_score": avg_score,
        "velocity": avg_score * 0.1,  # pseudo-velocity
        "shock": abs(avg_score) if abs(avg_score) > 0.8 else 0.0,
        "source_agreement": 1.0 if len(set(e.source for e in events)) > 1 else 0.5,
        "freshness": 1.0,
        "news_volume": float(len(events))
    }
