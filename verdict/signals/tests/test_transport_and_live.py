from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone

from verdict.signals.transport import retry
from verdict.signals.cmc import CMCClient, build_signal

# --------------------------------------------------------------------------- #
# Retry Tests
# --------------------------------------------------------------------------- #
def test_retry_success_first_attempt():
    calls = 0
    def fn():
        nonlocal calls
        calls += 1
        return "success"
    
    res = retry(fn, attempts=3)
    assert res == "success"
    assert calls == 1


def test_retry_eventual_success():
    calls = 0
    sleeps = []
    def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("fail")
        return "success"
    
    res = retry(fn, attempts=3, sleep=sleeps.append)
    assert res == "success"
    assert calls == 3
    assert sleeps == [0.2, 0.4]  # 0.2 * (2**0) -> 0.2, 0.2 * (2**1) -> 0.4


def test_retry_raises_after_max_attempts():
    calls = 0
    sleeps = []
    def fn():
        nonlocal calls
        calls += 1
        raise ValueError(f"fail {calls}")
        
    with pytest.raises(ValueError, match="fail 3"):
        retry(fn, attempts=3, sleep=sleeps.append)
    assert calls == 3
    assert sleeps == [0.2, 0.4]


# --------------------------------------------------------------------------- #
# Live Integration Tests (marked live, skipped by default)
# --------------------------------------------------------------------------- #
@pytest.mark.live
def test_live_quotes():
    if not (os.environ.get("CMC_MCP_API_KEY") or os.environ.get("CMC_PRO_API_KEY")):
        pytest.skip("No live CMC API keys found in environment")
        
    client = CMCClient.from_env()
    quotes = client.quotes(["BNB/USDT"])
    assert "BNB/USDT" in quotes
    assert isinstance(quotes["BNB/USDT"], float)
    assert quotes["BNB/USDT"] > 0.0


@pytest.mark.live
def test_live_build_signal():
    if not (os.environ.get("CMC_MCP_API_KEY") or os.environ.get("CMC_PRO_API_KEY")):
        pytest.skip("No live CMC API keys found in environment")
        
    client = CMCClient.from_env()
    sig = build_signal("BNB/USDT", client)
    assert sig.symbol == "BNB/USDT"
    assert sig.price > 0.0
    assert "rsi" in sig.indicators
    assert sig.indicators["rsi"] > 0.0
    assert sig.source in ("cmc-mcp", "cmc-mcp-degraded", "cmc-rest", "cmc-rest-degraded")
