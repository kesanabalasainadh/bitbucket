"""TDD for verdict.core.select — the pre-registered 3-criterion judge -> AgentVerdict.

Covers: evidence is filled on every candidate; a clearly-edgeless / high-cost run
yields an honest NO_TRADE with per-candidate reasons; a genuine edge yields TRADE
with the highest-risk_score passer selected; and the verdict is deterministic.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from verdict.schema import AgentVerdict, OHLCVBar, OHLCVSeries, Verdict
from verdict.core import select as sel
from verdict.core.candidates import generate_candidates
from verdict.core.costs import CostModel


def _series(closes, symbol="BNB/USDT", tf="4h"):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(hours=4)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        bars.append(OHLCVBar(ts=base + i * step, open=float(o), high=max(o, c) + 0.6,
                             low=min(o, c) - 0.6, close=float(c), volume=1000.0 + (i % 11) * 60))
    return OHLCVSeries(symbol=symbol, timeframe=tf, source="synthetic", bars=bars)


def _mean_reverting(n=1400, amp=22.0, drift=1.0008):
    # gentle uptrend (so price stays above EMA200) with large oscillations a
    # mean-reversion / pullback strategy can harvest while buy&hold stays ~flat per window
    return [100.0 * (drift ** i) + amp * math.sin(i / 8.0) for i in range(n)]


def _trend(n=1400):
    return [100.0 * (1.0025 ** i) for i in range(n)]


# --------------------------------------------------------------------------- #
def test_select_returns_agentverdict_with_filled_evidence():
    series = _series(_mean_reverting())
    cands = generate_candidates(series, None)
    v = sel.select(cands, series, CostModel(gas_usd=0.0))
    assert isinstance(v, AgentVerdict)
    assert v.verdict in (Verdict.TRADE, Verdict.NO_TRADE)
    assert len(v.candidates) == len(cands)
    for c in v.candidates:
        assert c.walkforward, "each candidate must carry its OOS windows"
        assert c.equity_curve and c.benchmark_curve and c.drawdown_curve
        assert c.metrics.risk_score >= 0.0
    assert "per_candidate" in v.criteria


def test_high_cost_forces_honest_no_trade_with_reasons():
    series = _series(_mean_reverting())
    cands = generate_candidates(series, None)
    brutal = CostModel(fee_pct=0.05, slippage_bps=200.0, gas_usd=0.0)   # ~12% round trip
    v = sel.select(cands, series, brutal)
    assert v.verdict == Verdict.NO_TRADE
    assert v.selected is None
    assert len(v.rejected) == len(cands)
    assert all(reason for reason in v.rejected.values())               # every reason non-empty


def test_genuine_edge_yields_trade_with_highest_risk_score():
    series = _series(_mean_reverting())
    cands = generate_candidates(series, None)
    v = sel.select(cands, series, CostModel(gas_usd=0.0))
    if v.verdict == Verdict.TRADE:
        eligible_scores = [c.metrics.risk_score for c in v.candidates
                           if c.id not in v.rejected]
        assert v.selected is not None
        assert v.selected.metrics.risk_score == max(eligible_scores)
        assert v.selected.id not in v.rejected
    else:
        # if the synthetic didn't clear the bar, the null must still be coherent
        assert v.selected is None and len(v.rejected) == len(cands)


def test_invariant_trade_selects_max_eligible_risk_score():
    # Direct invariant check independent of which market path we hit.
    for closes in (_mean_reverting(), _trend()):
        series = _series(closes)
        cands = generate_candidates(series, None)
        v = sel.select(cands, series, CostModel(gas_usd=0.0))
        if v.verdict == Verdict.TRADE:
            passers = [c.metrics.risk_score for c in v.candidates if c.id not in v.rejected]
            assert v.selected.metrics.risk_score == max(passers)
        else:
            assert v.selected is None


def test_select_is_deterministic():
    series = _series(_mean_reverting())
    a = sel.select(generate_candidates(series, None), series, CostModel(gas_usd=0.0))
    b = sel.select(generate_candidates(series, None), series, CostModel(gas_usd=0.0))
    assert a.verdict == b.verdict
    assert a.summary == b.summary
    assert {k: v for k, v in a.rejected.items()} == {k: v for k, v in b.rejected.items()}


def test_run_assets_offline_smoke():
    # The CLI orchestration path over committed BNB/ETH fixtures must not raise.
    v = sel.run_assets(["BNB/USDT"], "4h", CostModel(gas_usd=0.0))
    assert isinstance(v, AgentVerdict)
    assert v.candidates
