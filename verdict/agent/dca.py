from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from verdict.core.matrix import DecisionMatrixResult, MatrixAction
from verdict.safety.schema import KillSwitchAction, KillSwitchResult
from verdict.sentiment.schema import SentimentSnapshot


class AgentTrait(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class AgentNarrative(BaseModel):
    trait: AgentTrait
    action: str
    dca_cadence: str
    allocation_pct: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str
    reasons: list[str]


_TRAIT_ALLOCATION = {
    AgentTrait.CONSERVATIVE: 0.5,
    AgentTrait.BALANCED: 1.0,
    AgentTrait.AGGRESSIVE: 1.5,
}


def narrate_dca(
    matrix: DecisionMatrixResult,
    sentiment: SentimentSnapshot,
    kill_switch: KillSwitchResult,
    *,
    trait: AgentTrait = AgentTrait.BALANCED,
) -> AgentNarrative:
    if kill_switch.action != KillSwitchAction.ALLOW:
        return AgentNarrative(
            trait=trait,
            action=MatrixAction.NO_TRADE.value,
            dca_cadence="paused",
            allocation_pct=0.0,
            confidence=0.0,
            narrative=f"{trait.value} agent is paused: {kill_switch.reason}. Risk gates cannot be bypassed.",
            reasons=list(matrix.reasons) + [kill_switch.reason],
        )

    base_alloc = {
        MatrixAction.TRADE: 8.0,
        MatrixAction.DCA: 4.0,
        MatrixAction.WAIT: 0.0,
        MatrixAction.NO_TRADE: 0.0,
    }[matrix.action]
    alloc = base_alloc * _TRAIT_ALLOCATION[trait] * (1.0 - 0.5 * sentiment.volatility_adjustment)
    alloc = min(12.0, max(0.0, alloc))

    if matrix.action == MatrixAction.TRADE:
        cadence = "one initial tranche, then weekly review"
    elif matrix.action == MatrixAction.DCA:
        cadence = "small weekly DCA while matrix remains above threshold"
    elif matrix.action == MatrixAction.WAIT:
        cadence = "wait for next candle and sentiment refresh"
    else:
        cadence = "paused"

    confidence = min(0.95, max(0.0, matrix.score / 100.0 * (0.7 + 0.3 * sentiment.confidence)))
    narrative = (
        f"{trait.value} agent chooses {matrix.action.value}: matrix score {matrix.score:.1f}/100, "
        f"sentiment {sentiment.sentiment_score:+.2f} at confidence {sentiment.confidence:.2f}. "
        f"Allocation is capped at {alloc:.2f}% and execution remains out of scope."
    )
    return AgentNarrative(
        trait=trait,
        action=matrix.action.value,
        dca_cadence=cadence,
        allocation_pct=round(alloc, 2),
        confidence=round(confidence, 2),
        narrative=narrative,
        reasons=list(matrix.reasons),
    )
