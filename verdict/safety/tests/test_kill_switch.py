from __future__ import annotations

from datetime import datetime, timedelta, timezone

from verdict.safety import evaluate_kill_switch
from verdict.safety.schema import KillSwitchAction, KillSwitchState


def test_kill_switch_locks_on_manual_stop():
    result = evaluate_kill_switch(manual_stop=True)
    assert result.state == KillSwitchState.LOCKED
    assert result.action == KillSwitchAction.DISABLE_TRADING
    assert "manual_stop" in result.triggered


def test_kill_switch_pauses_on_stale_data():
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    result = evaluate_kill_switch(data_ts=now - timedelta(hours=3), now=now)
    assert result.state == KillSwitchState.PAUSED
    assert result.action == KillSwitchAction.FORCE_HOLD
    assert "data_stale" in result.triggered
