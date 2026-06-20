"""
Single source of truth for NSE equity transaction costs.

Two variants:
- DELIVERY (CNC, T+1 settlement) — used by swing strategies.
- INTRADAY (MIS, square-off same day) — used by the intraday engine.

Every rate is configurable. Defaults match Upstox + NSE schedules valid
as of mid-2026 — if SEBI/exchange tariffs change, update only this
module.

References:
- Upstox brokerage: https://upstox.com/brokerage-charges/
- STT/CTT, exchange txn, SEBI fee: NSE circulars.
- Stamp duty: Govt. of India schedule.
- DP charges: CDSL ₹13 + Upstox ₹5.50 ≈ ₹18.50 + 18% GST per
  scrip-day on delivery sell only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CostModel:
    """Round-trip transaction cost calculator for one NSE equity trade.

    All ratio fields are decimal (0.001 = 0.1%). All flat fields are INR.
    """

    # Brokerage: per-leg min(flat, value * pct).
    # Upstox CNC delivery: ₹20 OR 2.5% whichever is LOWER.
    # Upstox MIS intraday: ₹20 OR 0.05% whichever is LOWER.
    brokerage_flat: float = 20.0
    brokerage_pct: float = 0.025  # 2.5% for delivery
    # If you've enabled Upstox's API promo, override brokerage_flat = 10.0.

    # STT: 0.1% on BOTH sides for CNC delivery; 0.025% on SELL side only for MIS.
    stt_buy_pct: float = 0.001     # 0.1% buy side (delivery only)
    stt_sell_pct: float = 0.001    # 0.1% sell side (delivery); MIS is 0.00025

    # NSE Exchange transaction charges (post-2024 schedule).
    exchange_txn_pct: float = 0.0000297    # 0.00297% on turnover

    # IPFT (Investor Protection Fund Trust).
    ipft_pct: float = 0.0000001            # Rs.0.10 per lakh = 0.00001% = 1e-7

    # SEBI fee: Rs.10 per crore turnover = 0.00001% = 1e-7.
    sebi_pct: float = 0.0000001

    # Stamp duty: 0.015% on BUY side only (delivery); MIS 0.003% buy only.
    stamp_duty_buy_pct: float = 0.00015

    # GST: 18% on (brokerage + exchange_txn + SEBI + IPFT).
    gst_pct: float = 0.18

    # DP charges: CDSL+Upstox per scrip-day on delivery SELL only. Flat.
    # Set 0.0 for MIS.
    dp_charge_flat: float = 18.50

    # Slippage (one-way, applied to fill price). 0.0005 = 0.05%.
    # The backtester applies this when computing fill_price; the cost model
    # only stores it so cost reports can report effective slippage cost too.
    slippage_pct: float = 0.0005

    # Optional human label for reports.
    label: str = "DELIVERY (CNC)"

    # ------------------------------------------------------------------
    # Brokerage
    # ------------------------------------------------------------------
    def _leg_brokerage(self, leg_value: float) -> float:
        return min(self.brokerage_flat, leg_value * self.brokerage_pct)

    # ------------------------------------------------------------------
    # Round-trip cost
    # ------------------------------------------------------------------
    def round_trip(
        self,
        qty: int,
        buy_price: float,
        sell_price: float,
    ) -> "CostBreakdown":
        """Return itemized round-trip costs for one buy + one sell of `qty` shares.

        Buy and sell prices are the *executed* prices (after slippage),
        not the theoretical signal prices. The model does not apply
        slippage itself.
        """
        buy_value = qty * buy_price
        sell_value = qty * sell_price
        turnover = buy_value + sell_value

        brokerage_buy = self._leg_brokerage(buy_value)
        brokerage_sell = self._leg_brokerage(sell_value)
        brokerage = brokerage_buy + brokerage_sell

        stt = buy_value * self.stt_buy_pct + sell_value * self.stt_sell_pct
        exchange_txn = turnover * self.exchange_txn_pct
        ipft = turnover * self.ipft_pct
        sebi = turnover * self.sebi_pct
        stamp = buy_value * self.stamp_duty_buy_pct

        # GST applies to brokerage + exchange txn + SEBI + IPFT (NOT to STT
        # or stamp duty — those are taxes already).
        gst = (brokerage + exchange_txn + sebi + ipft) * self.gst_pct

        # DP charges include 18% GST per CDSL invoice line.
        dp = self.dp_charge_flat * (1.0 + self.gst_pct) if self.dp_charge_flat > 0 else 0.0

        total = brokerage + stt + exchange_txn + ipft + sebi + stamp + gst + dp

        return CostBreakdown(
            brokerage=brokerage,
            stt=stt,
            exchange_txn=exchange_txn,
            ipft=ipft,
            sebi=sebi,
            stamp_duty=stamp,
            gst=gst,
            dp_charges=dp,
            total=total,
        )

    def total(self, qty: int, buy_price: float, sell_price: float) -> float:
        """Convenience: return only total round-trip cost."""
        return self.round_trip(qty, buy_price, sell_price).total


@dataclass(frozen=True)
class CostBreakdown:
    """Itemized round-trip cost for one trade."""
    brokerage: float
    stt: float
    exchange_txn: float
    ipft: float
    sebi: float
    stamp_duty: float
    gst: float
    dp_charges: float
    total: float

    def as_dict(self) -> dict:
        return {
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "ipft": round(self.ipft, 4),
            "sebi": round(self.sebi, 4),
            "stamp_duty": round(self.stamp_duty, 2),
            "gst": round(self.gst, 2),
            "dp_charges": round(self.dp_charges, 2),
            "total": round(self.total, 2),
        }


# ---------------------------------------------------------------------------
# Cost-aware entry quality gate
# ---------------------------------------------------------------------------

def target_clears_costs(
    qty: int,
    entry_price: float,
    target_price: float,
    cost_model: CostModel,
    multiple: float = 3.0,
) -> bool:
    """True iff the round-trip cost at the planned target is cleared
    ``multiple`` times by the planned profit.

    A swing position whose target profit can't pay for its own round-trip
    costs more than `multiple` times has negative expected value once
    realistic slippage and timing noise are added back in. Default
    multiple = 3.0 (Kesana spec): if the profit target is less than 3x
    the round-trip cost, the position is not taken.

    This is intentionally a hard gate (not a soft warning) — the
    backtester and the live engine both refuse the entry.
    """
    if qty <= 0 or entry_price <= 0 or target_price <= entry_price:
        return False
    profit_potential = (target_price - entry_price) * qty
    cost_at_target = cost_model.total(qty, entry_price, target_price)
    if cost_at_target <= 0:
        return profit_potential > 0
    return profit_potential >= multiple * cost_at_target


# ---------------------------------------------------------------------------
# Pre-canned variants
# ---------------------------------------------------------------------------

DELIVERY_CNC = CostModel(label="DELIVERY (CNC)")

INTRADAY_MIS = CostModel(
    brokerage_pct=0.0005,        # 0.05% for MIS (Upstox)
    stt_buy_pct=0.0,             # STT only on MIS sell side
    stt_sell_pct=0.00025,        # 0.025% sell side
    stamp_duty_buy_pct=0.00003,  # 0.003% buy side for intraday
    dp_charge_flat=0.0,          # No DP charges on MIS
    label="INTRADAY (MIS)",
)
