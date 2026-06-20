"""
verdict.core.costs — crypto / DEX transaction cost model.

This replaces the NSE charge stack (STT / DP / GST / SEBI / stamp) from the
legacy engine with the costs a crypto trade actually pays:

    round-trip cost = 2 legs * ( notional * (LP/taker fee + slippage) + gas )

The cost model serves two jobs (both come straight from ``CONTRACTS.md``):

  * ``round_trip_cost(notional_usd)`` — the dollars a full enter+exit pays;
    the backtester deducts this from every trade's gross P&L.
  * ``clears_costs(expected_profit_usd, notional_usd, k)`` — the pre-trade
    entry-quality gate. A trade whose expected profit can't clear its own
    round-trip cost ``k`` times over has negative expected value once real
    slippage/timing noise is added back, so the engine refuses it. This is
    the crypto port of the legacy ``target_clears_costs`` gate.

Determinism: pure arithmetic, no I/O, frozen dataclass — identical inputs
always yield identical costs (judges re-run the engine).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Round-trip cost calculator for one crypto position (enter + exit).

    Fields:
        fee_pct:       per-leg LP/taker fee as a fraction (PancakeSwap v2 = 0.0025).
        slippage_bps:  per-leg slippage in basis points (30 bps = 0.30%).
        gas_usd:       flat gas paid per swap leg in USD (BSC is cheap; default 0
                       for CEX-candle backtests, set it for on-chain execution).
        label:         human description echoed onto the StrategySpec.cost_model.
    """

    fee_pct: float = 0.0025
    slippage_bps: float = 30.0
    gas_usd: float = 0.0
    label: str = "PancakeSwap v2: 0.25% fee + 30bps slippage"

    # ------------------------------------------------------------------ #
    # Costs
    # ------------------------------------------------------------------ #
    def _leg_rate(self) -> float:
        """Proportional cost charged on each leg's notional (fee + slippage)."""
        return self.fee_pct + self.slippage_bps / 10_000.0

    def leg_cost(self, notional_usd: float) -> float:
        """Cost of a single swap (one side of the round trip)."""
        return notional_usd * self._leg_rate() + self.gas_usd

    def round_trip_cost(self, notional_usd: float) -> float:
        """Total dollar cost to enter AND exit a ``notional_usd`` position."""
        return 2.0 * self.leg_cost(notional_usd)

    def round_trip_cost_frac(self, notional_usd: float) -> float:
        """Round-trip cost expressed as a fraction of notional.

        For a pure-proportional model this is just ``2 * leg_rate``; with gas it
        rises as notional shrinks. Returns ``inf`` for a non-positive notional
        so callers never divide a real profit by a phantom zero-cost trade.
        """
        if notional_usd <= 0:
            return float("inf")
        return self.round_trip_cost(notional_usd) / notional_usd

    # ------------------------------------------------------------------ #
    # Entry-quality gate (crypto port of target_clears_costs)
    # ------------------------------------------------------------------ #
    def clears_costs(
        self,
        expected_profit_usd: float,
        notional_usd: float,
        k: float = 3.0,
    ) -> bool:
        """True iff expected profit clears round-trip cost at least ``k`` times.

        A hard gate, not a soft warning: the backtester and live engine both
        refuse the entry when this is False.
        """
        if notional_usd <= 0 or expected_profit_usd <= 0:
            return False
        return expected_profit_usd >= k * self.round_trip_cost(notional_usd)


# --------------------------------------------------------------------------- #
# Pre-canned models
# --------------------------------------------------------------------------- #

# Track-1 execution venue: PancakeSwap v2 LP fee + a conservative slippage haircut.
PANCAKESWAP_V2 = CostModel(
    fee_pct=0.0025,
    slippage_bps=30.0,
    gas_usd=0.0,
    label="PancakeSwap v2: 0.25% fee + 30bps slippage",
)

# CEX spot reference (our historical candles are CEX-sourced). Lower fees than a
# DEX — used when we want the cost floor of a centralized venue.
BINANCE_SPOT = CostModel(
    fee_pct=0.0010,
    slippage_bps=5.0,
    gas_usd=0.0,
    label="Binance spot: 0.10% fee + 5bps slippage",
)


__all__ = ["CostModel", "PANCAKESWAP_V2", "BINANCE_SPOT"]
