from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from verdict.schema import AgentVerdict, Verdict
from verdict.sentiment.schema import SentimentSnapshot


class MatrixAction(str, Enum):
    TRADE = "TRADE"
    WAIT = "WAIT"
    DCA = "DCA"
    NO_TRADE = "NO_TRADE"


class DecisionMatrixResult(BaseModel):
    action: MatrixAction
    score: float = Field(ge=0.0, le=100.0)
    weights: dict[str, float]
    components: dict[str, float]
    reasons: list[str]


DEFAULT_WEIGHTS = {
    "trend": 35.0,
    "cost": 20.0,
    "sentiment": 15.0,
    "risk": 20.0,
    "momentum": 10.0,
}


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _component_inputs(verdict: AgentVerdict, sentiment: SentimentSnapshot, cost_clear: bool = True) -> dict[str, float]:
    selected = verdict.selected
    best = selected or max(verdict.candidates, key=lambda c: c.metrics.risk_score, default=None)
    if best is None:
        return {"trend": 0.0, "cost": 0.0, "sentiment": 0.5, "risk": 0.0, "momentum": 0.0}

    m = best.metrics
    pass_rates = []
    for candidate in verdict.candidates:
        per = verdict.criteria.get("per_candidate", {}).get(candidate.id, {})
        if "window_pass_rate" in per:
            pass_rates.append(float(per["window_pass_rate"]))
    pass_rate = max(pass_rates) if pass_rates else 0.0
    sentiment_component = 0.5 + 0.5 * sentiment.sentiment_score * sentiment.confidence
    return {
        "trend": _bounded(pass_rate),
        "cost": 1.0 if cost_clear else 0.0,
        "sentiment": _bounded(sentiment_component),
        "risk": _bounded(1.0 - m.max_drawdown / 40.0),
        "momentum": _bounded(max(m.sharpe_ratio, 0.0) / 3.0),
    }


def decide_matrix(
    verdict: AgentVerdict,
    sentiment: SentimentSnapshot,
    *,
    weights: dict[str, float] | None = None,
    cost_clear: bool = True,
    risk_blocked: bool = False,
) -> DecisionMatrixResult:
    weights = dict(weights or DEFAULT_WEIGHTS)
    total_weight = sum(weights.values()) or 1.0
    components = _component_inputs(verdict, sentiment, cost_clear=cost_clear)
    score = sum(components[k] * weights.get(k, 0.0) for k in components) / total_weight * 100.0
    reasons: list[str] = []

    if risk_blocked:
        action = MatrixAction.NO_TRADE
        reasons.append("risk gate blocked the strategy before allocation")
    elif verdict.verdict == Verdict.TRADE and score >= 70.0:
        action = MatrixAction.TRADE
        reasons.append("candidate cleared validation and matrix score is strong")
    elif score >= 55.0 and sentiment.confidence >= 0.25:
        action = MatrixAction.DCA
        reasons.append("edge is not strong enough for trade approval, but conditions support cautious DCA")
    elif score >= 40.0:
        action = MatrixAction.WAIT
        reasons.append("mixed evidence supports waiting for confirmation")
    else:
        action = MatrixAction.NO_TRADE
        reasons.append("matrix score is too weak after trend, cost, sentiment, and risk checks")

    if sentiment.volatility_adjustment > 0.35:
        reasons.append("sentiment volatility adjustment requires reduced allocation")
    if verdict.verdict == Verdict.NO_TRADE:
        reasons.append("core validator did not approve a strategy")

    return DecisionMatrixResult(
        action=action,
        score=round(score, 2),
        weights=weights,
        components={k: round(v, 4) for k, v in components.items()},
        reasons=reasons,
    )
