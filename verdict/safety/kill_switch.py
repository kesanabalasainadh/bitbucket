from __future__ import annotations

from datetime import datetime, timedelta, timezone

from verdict.safety.schema import KillSwitchAction, KillSwitchResult, KillSwitchState
from verdict.sentiment.schema import SentimentSnapshot


def evaluate_kill_switch(
    *,
    max_drawdown_pct: float = 0.0,
    sentiment: SentimentSnapshot | None = None,
    realized_volatility_pct: float = 0.0,
    api_ok: bool = True,
    data_ts: datetime | None = None,
    manual_stop: bool = False,
    round_trip_cost_pct: float = 0.0,
    now: datetime | None = None,
    max_allowed_drawdown_pct: float = 25.0,
    max_data_age_minutes: int = 90,
    max_volatility_pct: float = 18.0,
    max_round_trip_cost_pct: float = 2.5,
) -> KillSwitchResult:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    triggered: list[str] = []

    if manual_stop:
        triggered.append("manual_stop")
    if max_drawdown_pct >= max_allowed_drawdown_pct:
        triggered.append("max_drawdown")
    if sentiment is not None and sentiment.sentiment_score <= -0.65 and sentiment.confidence >= 0.35:
        triggered.append("sentiment_collapse")
    if realized_volatility_pct >= max_volatility_pct:
        triggered.append("extreme_volatility")
    if not api_ok:
        triggered.append("api_failure")
    if data_ts is not None:
        if data_ts.tzinfo is None:
            data_ts = data_ts.replace(tzinfo=timezone.utc)
        if now - data_ts.astimezone(timezone.utc) > timedelta(minutes=max_data_age_minutes):
            triggered.append("data_stale")
    if round_trip_cost_pct >= max_round_trip_cost_pct:
        triggered.append("cost_spike")

    if manual_stop or "max_drawdown" in triggered:
        state = KillSwitchState.LOCKED
        action = KillSwitchAction.DISABLE_TRADING
    elif triggered:
        state = KillSwitchState.PAUSED
        action = KillSwitchAction.FORCE_HOLD
    else:
        state = KillSwitchState.ACTIVE
        action = KillSwitchAction.ALLOW

    reason = "no kill-switch triggers active" if not triggered else "blocked by " + ", ".join(triggered)
    return KillSwitchResult(state=state, action=action, triggered=triggered, reason=reason)
