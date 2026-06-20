"""TDD for verdict.core.candidates — deterministic, grammar-expressible specs.

The load-bearing guarantee: EVERY rule a candidate emits must be evaluable by
verdict.core.rules (so the backtester scores it 1:1) and every stop/take-profit
must parse. If a candidate could emit a rule the engine can't read, the whole
"deterministic, inspectable" claim collapses.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from verdict.schema import OHLCVBar, OHLCVSeries, RiskProfile, Signal, StrategyMetrics, StrategySpec
from verdict.core import rules
from verdict.core import candidates as cand
from verdict.core.backtest import backtest
from verdict.core.costs import CostModel


def _series(n=400):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(hours=4)
    closes = [100 * (1.002 ** i) + 8 * math.sin(i / 7.0) for i in range(n)]
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        bars.append(OHLCVBar(ts=base + i * step, open=float(o), high=max(o, c) + 0.6,
                             low=min(o, c) - 0.6, close=float(c), volume=1000.0 + (i % 13) * 50))
    return OHLCVSeries(symbol="BNB/USDT", timeframe="4h", source="ccxt-binance", bars=bars)


def test_generates_at_least_three_distinct_archetypes():
    specs = cand.generate_candidates(_series(), None)
    assert len(specs) >= 3
    assert len({s.id for s in specs}) == len(specs)          # unique ids
    assert len({s.name for s in specs}) == len(specs)        # distinct names


def _signal(btc_dominance, symbol="BNB/USDT"):
    return Signal(ts=datetime(2026, 1, 1, tzinfo=timezone.utc), symbol=symbol,
                  price=600.0, btc_dominance=btc_dominance, regime="neutral")


def test_btc_dominance_gate_consumes_cmc_signal():
    """CMC btc_dominance is actually consumed: high dominance tightens a non-BTC alt
    (conservative + 3-of-3 confluence, echoed into reasoning); BTC and the offline
    None-path are unaffected. Makes the 'btc_dominance feeds the regime' claim true."""
    s = _series()
    hi = next(c for c in cand.generate_candidates(s, _signal(58.0)) if c.id.startswith("momentum"))
    assert hi.risk_profile == RiskProfile.CONSERVATIVE
    assert any("at_least 3 of" in r for r in hi.entry_rules)
    assert "BTC dominance" in hi.reasoning

    lo = next(c for c in cand.generate_candidates(s, _signal(48.0)) if c.id.startswith("momentum"))
    assert lo.risk_profile == RiskProfile.BALANCED
    assert any("at_least 2 of" in r for r in lo.entry_rules)

    # BTC itself: high dominance is a tailwind, not a headwind -> no penalty.
    btc_series = OHLCVSeries(symbol="BTC/USDT", timeframe="4h", source=s.source, bars=s.bars)
    btc = next(c for c in cand.generate_candidates(btc_series, _signal(58.0, "BTC/USDT"))
               if c.id.startswith("momentum"))
    assert btc.risk_profile == RiskProfile.BALANCED
    assert any("at_least 2 of" in r for r in btc.entry_rules)

    # Offline / None signal -> no-op (degrades gracefully).
    off = next(c for c in cand.generate_candidates(s, None) if c.id.startswith("momentum"))
    assert any("at_least 2 of" in r for r in off.entry_rules)


def test_assets_and_timeframe_propagate():
    series = _series()
    for s in cand.generate_candidates(series, None):
        assert s.assets == [series.symbol]
        assert s.timeframe == series.timeframe


def test_every_entry_and_exit_rule_is_grammar_expressible():
    series = _series()
    df = rules.prepare(series.to_dataframe())
    t = len(df) - 1
    for s in cand.generate_candidates(series, None):
        for r in s.entry_rules:
            assert isinstance(rules.evaluate_rule(df, t, r), bool), r
        for r in rules.grammar_exit_rules(s.exit_rules):
            assert isinstance(rules.evaluate_rule(df, t, r), bool), r
        assert rules.parse_exit_level(s.stop_loss) is not None, s.stop_loss
        assert rules.parse_exit_level(s.take_profit) is not None, s.take_profit


def test_specs_are_backtestable():
    series = _series()
    costs = CostModel(gas_usd=0.0)
    for s in cand.generate_candidates(series, None):
        m = backtest(series, s, costs)
        assert isinstance(m, StrategyMetrics)


def test_risk_off_signal_tightens_candidates():
    series = _series()
    sig_off = Signal(ts=datetime(2026, 6, 19, tzinfo=timezone.utc), symbol="BNB/USDT",
                     price=600.0, regime="risk_off", fear_greed=18.0, funding_rate=0.0003)
    neutral = cand.generate_candidates(series, None)
    risk_off = cand.generate_candidates(series, sig_off)
    # conservative risk profile + smaller size in risk_off
    assert all(s.risk_profile == RiskProfile.CONSERVATIVE for s in risk_off)
    assert all(s.risk_profile == RiskProfile.BALANCED for s in neutral)
    assert "1%" in risk_off[0].position_size and "2%" in neutral[0].position_size
    # momentum trend filter strengthens ema_100 -> ema_200
    assert any("ema_200" in r for r in risk_off[0].entry_rules)
    assert any("ema_100" in r for r in neutral[0].entry_rules)


def test_generation_is_deterministic():
    series = _series()
    a = cand.generate_candidates(series, None)
    b = cand.generate_candidates(series, None)
    assert [s.model_dump(exclude={"created_at"}) for s in a] == \
           [s.model_dump(exclude={"created_at"}) for s in b]
