"""TDD for verdict.core.costs — the crypto/DEX cost model + cost-clearance gate.

The cost model is what makes VERDICT's backtest honest: every round trip pays
LP/taker fees + slippage (+ optional gas), and the entry-quality gate refuses
trades whose expected profit can't clear those costs by a margin ``k``.
"""
from __future__ import annotations

import pytest

from verdict.core.costs import CostModel, PANCAKESWAP_V2, BINANCE_SPOT


def test_round_trip_cost_is_two_legs_of_fee_plus_slippage():
    # 0.25% fee + 30bps slippage, no gas. One round trip = enter + exit.
    # per leg = notional * (0.0025 + 0.0030); two legs on $10k = 110.0
    m = CostModel(fee_pct=0.0025, slippage_bps=30.0, gas_usd=0.0)
    assert m.round_trip_cost(10_000.0) == pytest.approx(110.0)


def test_gas_is_charged_once_per_leg():
    m = CostModel(fee_pct=0.0025, slippage_bps=30.0, gas_usd=1.5)
    # adds 2 * 1.5 on top of the 110.0 fee+slippage
    assert m.round_trip_cost(10_000.0) == pytest.approx(113.0)


def test_round_trip_cost_frac_is_cost_over_notional():
    m = CostModel(fee_pct=0.0025, slippage_bps=30.0, gas_usd=0.0)
    assert m.round_trip_cost_frac(10_000.0) == pytest.approx(0.011)


def test_clears_costs_passes_at_exactly_k_times_cost():
    m = CostModel(fee_pct=0.0025, slippage_bps=30.0, gas_usd=0.0)
    cost = m.round_trip_cost(10_000.0)  # 110.0
    assert m.clears_costs(3.0 * cost, 10_000.0, k=3.0) is True
    assert m.clears_costs(3.0 * cost - 0.01, 10_000.0, k=3.0) is False


def test_clears_costs_rejects_nonpositive_profit_or_notional():
    m = PANCAKESWAP_V2
    assert m.clears_costs(0.0, 10_000.0) is False
    assert m.clears_costs(-50.0, 10_000.0) is False
    assert m.clears_costs(100.0, 0.0) is False
    assert m.clears_costs(100.0, -1.0) is False


def test_default_pancakeswap_v2_preset():
    assert PANCAKESWAP_V2.fee_pct == pytest.approx(0.0025)
    assert PANCAKESWAP_V2.slippage_bps == pytest.approx(30.0)
    assert "PancakeSwap" in PANCAKESWAP_V2.label


def test_binance_spot_preset_is_cheaper_than_dex():
    # CEX spot fees are lower than DEX LP fees — sanity that presets differ.
    assert BINANCE_SPOT.round_trip_cost(10_000.0) < PANCAKESWAP_V2.round_trip_cost(10_000.0)


def test_cost_model_is_immutable():
    m = CostModel()
    with pytest.raises(Exception):
        m.fee_pct = 0.5  # frozen dataclass
