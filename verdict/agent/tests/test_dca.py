from __future__ import annotations

from datetime import datetime, timezone

from verdict.agent import AgentTrait, narrate_dca
from verdict.core.matrix import DecisionMatrixResult, MatrixAction
from verdict.safety.schema import KillSwitchAction, KillSwitchResult, KillSwitchState
from verdict.sentiment.schema import SentimentSnapshot


def _matrix(action=MatrixAction.DCA):
    return DecisionMatrixResult(
        action=action, score=62.0, weights={}, components={}, reasons=["test reason"]
    )


def _sent():
    return SentimentSnapshot(
        symbol="BNB", ts=datetime(2026, 6, 20, tzinfo=timezone.utc),
        sentiment_score=0.1, confidence=0.6, headline_count=4,
        volatility_adjustment=0.1, freshness=1.0,
    )


def test_dca_agent_never_bypasses_kill_switch():
    kill = KillSwitchResult(
        state=KillSwitchState.PAUSED, action=KillSwitchAction.FORCE_HOLD,
        triggered=["api_failure"], reason="blocked by api_failure",
    )
    out = narrate_dca(_matrix(MatrixAction.TRADE), _sent(), kill, trait=AgentTrait.AGGRESSIVE)
    assert out.action == MatrixAction.NO_TRADE.value
    assert out.allocation_pct == 0.0


def test_personality_changes_allocation_not_action():
    kill = KillSwitchResult(state=KillSwitchState.ACTIVE, action=KillSwitchAction.ALLOW)
    conservative = narrate_dca(_matrix(), _sent(), kill, trait=AgentTrait.CONSERVATIVE)
    aggressive = narrate_dca(_matrix(), _sent(), kill, trait=AgentTrait.AGGRESSIVE)
    assert conservative.action == aggressive.action == MatrixAction.DCA.value
    assert conservative.allocation_pct < aggressive.allocation_pct
