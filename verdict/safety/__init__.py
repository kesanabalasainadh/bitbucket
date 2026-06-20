"""Risk gates and kill-switch primitives."""

from verdict.safety.kill_switch import evaluate_kill_switch
from verdict.safety.schema import KillSwitchAction, KillSwitchResult, KillSwitchState

__all__ = ["evaluate_kill_switch", "KillSwitchAction", "KillSwitchResult", "KillSwitchState"]
