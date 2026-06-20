from __future__ import annotations

from datetime import datetime, timezone

from verdict.core.matrix import MatrixAction, decide_matrix
from verdict.schema import AgentVerdict, StrategyMetrics, StrategySpec, Verdict
from verdict.sentiment.schema import SentimentSnapshot


def _spec(score=80.0):
    return StrategySpec(
        id="s", name="s", description="s", assets=["BNB/USDT"], timeframe="4h",
        horizon="swing", lookback=100, metrics=StrategyMetrics(
            return_pct=10, sharpe_ratio=2, win_rate=0.6, max_drawdown=8, risk_score=score,
        ),
    )


def _sent(score=0.2, confidence=0.8):
    return SentimentSnapshot(
        symbol="BNB", ts=datetime(2026, 6, 20, tzinfo=timezone.utc),
        sentiment_score=score, confidence=confidence, headline_count=5,
        volatility_adjustment=abs(score) * confidence, freshness=1.0,
    )


def test_matrix_never_trades_when_risk_blocked():
    verdict = AgentVerdict(verdict=Verdict.TRADE, selected=_spec(), candidates=[_spec()])
    result = decide_matrix(verdict, _sent(), risk_blocked=True)
    assert result.action == MatrixAction.NO_TRADE
    assert "risk gate" in result.reasons[0]


def test_matrix_explains_no_trade_core_verdict():
    verdict = AgentVerdict(verdict=Verdict.NO_TRADE, selected=None, candidates=[_spec(20)])
    result = decide_matrix(verdict, _sent(score=-0.2, confidence=0.7))
    assert result.action in (MatrixAction.WAIT, MatrixAction.NO_TRADE, MatrixAction.DCA)
    assert any("core validator" in reason for reason in result.reasons)
