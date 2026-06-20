"""Narrative-only DCA agent.

This package does not execute trades. It explains matrix decisions and allocation
posture after risk gates have run.
"""

from verdict.agent.dca import AgentNarrative, AgentTrait, narrate_dca

__all__ = ["AgentNarrative", "AgentTrait", "narrate_dca"]
