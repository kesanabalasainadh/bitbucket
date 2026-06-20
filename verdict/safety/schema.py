from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class KillSwitchState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    LOCKED = "LOCKED"


class KillSwitchAction(str, Enum):
    ALLOW = "ALLOW"
    FORCE_HOLD = "FORCE_HOLD"
    DISABLE_TRADING = "DISABLE_TRADING"


class KillSwitchResult(BaseModel):
    state: KillSwitchState
    action: KillSwitchAction
    triggered: list[str] = Field(default_factory=list)
    reason: str = ""
