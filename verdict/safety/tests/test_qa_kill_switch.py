from __future__ import annotations
import pytest
from verdict.safety import evaluate_kill_switch
from verdict.safety.schema import KillSwitchState, KillSwitchAction

def test_kill_switch_drawdown_boundaries():
    # threshold is max_allowed_drawdown_pct (default 25.0)
    # Just below
    res_below = evaluate_kill_switch(max_drawdown_pct=24.9)
    assert res_below.state == KillSwitchState.ACTIVE
    assert res_below.action == KillSwitchAction.ALLOW

    # At threshold
    res_at = evaluate_kill_switch(max_drawdown_pct=25.0)
    assert res_at.state == KillSwitchState.LOCKED
    assert res_at.action == KillSwitchAction.DISABLE_TRADING

    # Just above
    res_above = evaluate_kill_switch(max_drawdown_pct=25.1)
    assert res_above.state == KillSwitchState.LOCKED
    assert res_above.action == KillSwitchAction.DISABLE_TRADING

def test_kill_switch_blocks_dca():
    # this is covered by test_dca_agent_never_bypasses_kill_switch but we assert state transition
    res = evaluate_kill_switch(max_drawdown_pct=26.0)
    assert res.state == KillSwitchState.LOCKED
    assert "max_drawdown" in res.triggered
