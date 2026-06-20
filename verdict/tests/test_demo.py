from __future__ import annotations

from verdict.agent import AgentTrait
from verdict.demo import run_demo


def test_demo_summary_is_clean_json_shape():
    payload = run_demo("BNB/USDT", "4h", AgentTrait.BALANCED)
    assert payload["scope"].startswith("Track-2")
    assert "market_data" in payload
    assert "sentiment" in payload
    assert "decision_matrix" in payload
    assert "kill_switch" in payload
    assert "dca_agent" in payload
