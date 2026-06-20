"""
Swing Backtester: Daily EMA Pullback + MACD Confirmation
=========================================================
Backtests a long-only swing strategy on daily bars derived from 1-min tick cache.

Key differences from intraday backtester:
- Aggregates 1-min ticks into daily OHLCV bars
- Positions span multiple trading days (2-10 day hold)
- Uses CNC delivery charges (STT 0.1% both sides, not 0.025% sell-only)
- Risk-based position sizing (risk 2% of capital per trade)
- Entry signal: ALL 6 conditions must pass (conjunction, not weighted ensemble)

Charge comparison:
- Intraday (MIS): ~Rs.26/trade on Rs.10k positions (0.27%)
- Delivery (CNC): ~Rs.46/trade on Rs.10k positions (0.46%)
- But swing targets 3-8% moves, so 0.46% charge = 6-15% of profit (much better)
"""

from __future__ import annotations

import logging
import math
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.cost_model import DELIVERY_CNC, CostModel, target_clears_costs
from src.backtest.engine_backtester import BacktestReport
from src.backtest.regime import (
    MarketTrend, RegimeConfig, RegimeDecision, VixRegime, classify_regime,
)
from src.strategy.swing_signal_generator import SwingSignalGenerator, SwingSignalType

logger = logging.getLogger(__name__)

try:
    from src.utils.ist_utils import IST
except ImportError:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Instrument tokens for our swing universe
# ---------------------------------------------------------------------------

SWING_TOKENS: Dict[str, str] = {
    "VEDL": "NSE_EQ|INE205A01025",
    "INDUSINDBK": "NSE_EQ|INE095A01012",
    "HINDALCO": "NSE_EQ|INE038A01020",
    "TATASTEEL": "NSE_EQ|INE081A01020",
}


# ---------------------------------------------------------------------------
# Swing position
# ---------------------------------------------------------------------------

@dataclass
class SwingPosition:
    """An open swing trade (long only)."""
    symbol: str
    entry_price: float
    qty: int
    stop_loss: float
    target: float
    entry_date: str          # YYYY-MM-DD
    entry_atr: float
    days_held: int = 0
    best_price: float = 0.0  # highest price since entry
    # Phase 4 / addendum §B & §D: regime + group at entry so reports
    # can break P&L down by VIX tier, trend, and universe group.
    entry_vix_regime: str = "NORMAL"
    entry_market_trend: str = "UNKNOWN"
    entry_group: str = "?"
    # Exit-redesign state. partial_taken=True after the partial-profit
    # half has been booked; ``original_qty`` preserves the entry qty so
    # report aggregates can attribute pnl correctly.
    partial_taken: bool = False
    original_qty: int = 0

    def __post_init__(self):
        if self.best_price == 0.0:
            self.best_price = self.entry_price
        if self.original_qty == 0:
            self.original_qty = self.qty


# ---------------------------------------------------------------------------
# Swing config
# ---------------------------------------------------------------------------

@dataclass
class SwingConfig:
    """All tunable swing strategy parameters."""
    budget: float = 30000.0
    max_positions: int = 3
    risk_per_trade_pct: float = 2.0   # risk 2% of capital per trade
    # Cap one position's capital deployment at this % of budget. Phase 2.
    max_position_pct: float = 20.0
    # Cost-aware entry quality gate: refuse trades whose target profit fails
    # to clear round-trip costs by at least this multiple. Phase 2 spec.
    min_profit_cost_multiple: float = 3.0

    # Strategy
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 100
    rsi_period: int = 14
    rsi_low: float = 40
    rsi_high: float = 65
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    pullback_zone_pct: float = 0.02
    volume_ma_period: int = 50
    volume_threshold: float = 0.8
    min_adx: int = 15
    entry_days: List[int] = field(default_factory=lambda: [0, 1, 2])

    # Risk
    sl_atr_mult: float = 1.5
    target_atr_mult: float = 3.0
    max_hold_days: int = 10
    stale_trade_days: int = 5
    max_weekly_loss_pct: float = 5.0
    max_vix: float = 18.0

    # Restrictions
    swing_restricted: List[str] = field(default_factory=list)
    earnings_blackout: Dict[str, str] = field(default_factory=dict)

    # Slippage
    slippage_pct: float = 0.05

    # ----------------- Exit-redesign experiment knobs -----------------
    # Defaults preserve baseline behaviour. Variants in
    # ``experiments/2026-06-11_exit_redesign.md`` flip these on.

    # Disable the fixed ATR target — exits are governed by SL, trailing
    # stop, and max_hold_days only. The cost gate uses the trailing
    # trigger price as the effective minimum-profit anchor.
    disable_fixed_target: bool = False

    # ATR-trailing stop. When best_price - entry >= trigger_mult * ATR,
    # the effective stop ratchets to best_price - distance_mult * ATR
    # (only moves up, never down).
    use_trailing_stop: bool = False
    trailing_trigger_atr_mult: float = 1.5
    trailing_distance_atr_mult: float = 1.0

    # Partial-profit exit. When best_price - entry >= trigger_mult * ATR
    # and partial has not yet been taken, sell ``partial_fraction`` of qty
    # at the trigger price (booked as a separate trade with reason
    # ``partial_profit``). The remainder continues on the trailing stop
    # using ``partial_trail_distance_atr_mult`` (defaults to the same
    # distance as the regular trailing stop).
    use_partial_profit: bool = False
    partial_profit_trigger_atr_mult: float = 1.5
    partial_profit_fraction: float = 0.5
    partial_trail_distance_atr_mult: float = 1.5

    def __post_init__(self):
        assert self.budget > 0, "Budget must be positive"
        assert self.sl_atr_mult > 0, "SL ATR multiplier must be positive"
        assert self.target_atr_mult > 0, "Target ATR multiplier must be positive"
        assert self.target_atr_mult > self.sl_atr_mult, "Target must be > SL"
        assert self.max_positions >= 1, "Must allow at least 1 position"
        assert 0 < self.risk_per_trade_pct <= 10, "Risk per trade must be 0-10%"

    @classmethod
    def from_yaml(cls, path: str) -> SwingConfig:
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        strategy = raw.get("strategy", {})
        risk = raw.get("risk", {})
        return cls(
            budget=raw.get("budget", 30000),
            max_positions=raw.get("max_positions", 3),
            risk_per_trade_pct=raw.get("risk_per_trade_pct", 2.0),
            max_position_pct=risk.get("max_position_pct",
                                       raw.get("max_position_pct", 20.0)),
            min_profit_cost_multiple=risk.get(
                "min_profit_cost_multiple",
                raw.get("min_profit_cost_multiple", 3.0),
            ),
            ema_fast=strategy.get("ema_fast", 20),
            ema_slow=strategy.get("ema_slow", 50),
            ema_trend=strategy.get("ema_trend", 100),
            rsi_period=strategy.get("rsi_period", 14),
            rsi_low=strategy.get("rsi_low", 40),
            rsi_high=strategy.get("rsi_high", 65),
            macd_fast=strategy.get("macd_fast", 12),
            macd_slow=strategy.get("macd_slow", 26),
            macd_signal=strategy.get("macd_signal", 9),
            pullback_zone_pct=strategy.get("pullback_zone_pct", 0.02),
            volume_ma_period=strategy.get("volume_ma_period", 50),
            volume_threshold=strategy.get("volume_threshold", 0.8),
            min_adx=strategy.get("min_adx", 15),
            entry_days=strategy.get("entry_days", [0, 1, 2]),
            sl_atr_mult=risk.get("sl_atr_mult", 1.5),
            target_atr_mult=risk.get("target_atr_mult", 3.0),
            max_hold_days=risk.get("max_hold_days", 10),
            stale_trade_days=risk.get("stale_trade_days", 5),
            max_weekly_loss_pct=risk.get("max_weekly_loss_pct", 5.0),
            max_vix=risk.get("max_vix", 18.0),
            swing_restricted=raw.get("swing_restricted", []),
            earnings_blackout=raw.get("earnings_blackout", {}),
            slippage_pct=raw.get("slippage_pct", 0.05),
        )

    def strategy_dict(self) -> Dict[str, Any]:
        """Return dict suitable for SwingSignalGenerator."""
        return {
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_trend": self.ema_trend,
            "rsi_period": self.rsi_period,
            "rsi_low": self.rsi_low,
            "rsi_high": self.rsi_high,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "pullback_zone_pct": self.pullback_zone_pct,
            "volume_ma_period": self.volume_ma_period,
            "volume_threshold": self.volume_threshold,
            "min_adx": self.min_adx,
            "entry_days": self.entry_days,
        }


# ---------------------------------------------------------------------------
# Swing Backtester
# ---------------------------------------------------------------------------

class SwingBacktester:
    """
    Backtest swing trading strategy on daily bars.

    Workflow:
    1. Aggregate 1-min tick data → daily OHLCV per symbol
    2. Walk forward day by day:
       a. Check exit conditions on open positions (SL, target, time, stale)
       b. Check entry signals on available symbols
    3. Compute BacktestReport

    Cost model: pluggable via the ``cost_model`` constructor arg. Defaults
    to the centralized DELIVERY_CNC model (see src/backtest/cost_model.py).
    """

    def __init__(self, config: SwingConfig,
                 cost_model: Optional[CostModel] = None,
                 vix_series: Optional[pd.Series] = None,
                 nifty_series: Optional[pd.Series] = None,
                 regime_config: Optional[RegimeConfig] = None,
                 symbol_to_group: Optional[Dict[str, str]] = None):
        self.cfg = config
        self.slippage = config.slippage_pct / 100.0
        self.signal_gen = SwingSignalGenerator(config.strategy_dict())
        self.cost_model = cost_model or DELIVERY_CNC
        # ``vix_series`` is a pd.Series indexed by date string (YYYY-MM-DD)
        # with India VIX daily closes. If provided and ``max_vix`` is set on
        # the config, the backtester refuses new entries on date T whenever
        # the most recent available VIX close (T-1) is >= ``max_vix``.
        # This mirrors the live engine's max_vix gate, but uses pre-decision
        # data only (no same-bar VIX leak).
        self.vix_series = vix_series
        # Phase 4 / addendum §B. Optional Nifty 50 daily close series and
        # RegimeConfig drive the VIX-tier + Nifty-SMA regime classifier.
        # When regime_config.enabled is False, the gate is a no-op — this
        # is how the walk-forward harness runs the "regime off" comparison
        # arm. ``symbol_to_group`` maps trading symbols to their universe
        # group name for the ELEVATED-blocks-high-beta rule.
        self.nifty_series = nifty_series
        self.regime_config = regime_config or RegimeConfig(enabled=False)
        self.symbol_to_group = symbol_to_group or {}

    # ------------------------------------------------------------------
    # Round-trip cost (delegates to CostModel)
    # ------------------------------------------------------------------

    def _estimate_charges(self, qty: int, buy_price: float, sell_price: float) -> float:
        """Estimate round-trip charges using the configured CostModel."""
        return self.cost_model.total(qty, buy_price, sell_price)

    # ------------------------------------------------------------------
    # VIX regime gate (uses T-1 close only)
    # ------------------------------------------------------------------

    def _vix_blocks_entry(self, date: str) -> bool:
        """True if VIX as-of close-of-day-before-`date` is >= max_vix.

        Only the most recent VIX close STRICTLY before ``date`` is consulted —
        so no same-bar regime leakage. If no VIX series was provided, the
        gate is a no-op (False).
        """
        if self.vix_series is None or self.cfg.max_vix is None:
            return False
        try:
            prior = self.vix_series.loc[:date]
            # Drop the current date if present so the gate is strictly T-1.
            prior = prior[prior.index < date]
            if prior.empty:
                return False
            last_close = float(prior.iloc[-1])
        except (KeyError, ValueError):
            return False
        return last_close >= float(self.cfg.max_vix)

    # ------------------------------------------------------------------
    # Aggregate 1-min ticks → daily OHLCV
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_to_daily(ticks_by_symbol: Dict[str, List[Dict]]) -> Dict[str, pd.DataFrame]:
        """
        Convert 1-min tick data to daily OHLCV bars.

        Returns {symbol: DataFrame} where DataFrame has columns:
            date, open, high, low, close, volume
        indexed by date string (YYYY-MM-DD).
        """
        daily_data: Dict[str, pd.DataFrame] = {}

        for symbol, ticks in ticks_by_symbol.items():
            if not ticks:
                continue

            df = pd.DataFrame(ticks)
            df["date"] = df["timestamp"].apply(lambda ts: ts.strftime("%Y-%m-%d"))

            daily = df.groupby("date").agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            ).sort_index()

            daily_data[symbol] = daily

        return daily_data

    # ------------------------------------------------------------------
    # Main backtest entry point
    # ------------------------------------------------------------------

    def run(self, ticks_by_symbol: Dict[str, List[Dict]],
            days: Optional[int] = None,
            compound: bool = False) -> BacktestReport:
        """
        Run swing backtest on pre-fetched 1-min tick data.

        Args:
            ticks_by_symbol: {symbol: [tick_dicts]} from cache or fetch_universe_data.
            days: Optional limit on number of trading days (from end).
            compound: If True, reinvest profits into position sizing (compounding).
        """
        # Aggregate to daily bars
        daily_data = self.aggregate_to_daily(ticks_by_symbol)
        if not daily_data:
            logger.error("No daily data after aggregation")
            return BacktestReport()

        # Get sorted union of all trading dates
        all_dates = sorted(set().union(
            *(df.index.tolist() for df in daily_data.values())
        ))
        if days:
            all_dates = all_dates[-days:]

        mode_str = "COMPOUND" if compound else "FIXED"
        logger.info(f"Swing backtest ({mode_str}): {len(all_dates)} trading days, "
                     f"{len(daily_data)} symbols")

        # Walk forward day by day
        open_positions: Dict[str, SwingPosition] = {}
        all_trades: List[Dict[str, Any]] = []
        daily_pnl: Dict[str, float] = {d: 0.0 for d in all_dates}
        # daily_invested[date] = capital deployed at start of `date` (sum of
        # entry_price * qty across positions held). Used for exposure_pct.
        daily_invested: Dict[str, float] = {d: 0.0 for d in all_dates}
        cumulative_pnl = 0.0  # tracks realized P&L for compounding
        budget_history: List[Tuple[str, float]] = []  # (date, effective_budget)
        # Counters surfaced in the report so the audit can see how many
        # candidate entries were rejected by each gate.
        skip_counters = {
            "min_profit": 0, "max_position_pct": 0, "vix_gate": 0,
            "regime_block_all": 0, "regime_block_group": 0,
        }
        # Regime decisions logged per scan-day so the walk-forward
        # report can break down P&L by regime.
        regime_log: Dict[str, Dict[str, Any]] = {}

        for date_idx, date in enumerate(all_dates):
            day_pnl = 0.0
            effective_budget = self.cfg.budget + cumulative_pnl if compound else self.cfg.budget

            # Snapshot capital deployed at start of day (before exits)
            daily_invested[date] = sum(p.entry_price * p.qty for p in open_positions.values())

            # --- Exit checks on open positions ---
            for sym in list(open_positions.keys()):
                pos = open_positions[sym]

                if sym not in daily_data or date not in daily_data[sym].index:
                    continue

                # Only count trading days (not weekends/holidays/missing data)
                pos.days_held += 1

                bar = daily_data[sym].loc[date]
                day_open = float(bar["open"])
                day_high = float(bar["high"])
                day_low = float(bar["low"])
                day_close = float(bar["close"])

                # Update best price
                pos.best_price = max(pos.best_price, day_high)

                # ----- Exit-redesign: partial profit (booked BEFORE the
                # main exit decision so the remainder can ride). Variants
                # C uses this.
                if (self.cfg.use_partial_profit and not pos.partial_taken
                        and pos.qty >= 2):
                    pp_trigger = (pos.entry_price
                                   + self.cfg.partial_profit_trigger_atr_mult
                                   * pos.entry_atr)
                    if day_high >= pp_trigger:
                        partial_qty = max(1, int(round(
                            pos.original_qty * self.cfg.partial_profit_fraction
                        )))
                        partial_qty = min(partial_qty, pos.qty - 1)
                        if partial_qty > 0:
                            partial_fill = round(
                                max(pp_trigger, day_open) * (1 - self.slippage), 2,
                            )
                            partial_charges = self._estimate_charges(
                                partial_qty, pos.entry_price, partial_fill,
                            )
                            partial_gross = (partial_fill - pos.entry_price) * partial_qty
                            partial_net = partial_gross - partial_charges
                            all_trades.append({
                                "symbol": sym,
                                "entry_price": pos.entry_price,
                                "exit_price": partial_fill,
                                "qty": partial_qty,
                                "gross_pnl": round(partial_gross, 2),
                                "charges": round(partial_charges, 2),
                                "pnl": round(partial_net, 2),
                                "entry_date": pos.entry_date,
                                "exit_date": date,
                                "days_held": pos.days_held,
                                "reason": "partial_profit",
                                "sl": pos.stop_loss,
                                "target": pos.target,
                                "atr": pos.entry_atr,
                                "entry_vix_regime": pos.entry_vix_regime,
                                "entry_market_trend": pos.entry_market_trend,
                                "entry_group": pos.entry_group,
                            })
                            day_pnl += partial_net
                            cumulative_pnl += partial_net
                            pos.qty -= partial_qty
                            pos.partial_taken = True

                # ----- Trailing-stop ratchet. Activates when best_price
                # is at least trigger_mult * ATR above entry. Stop only
                # ratchets UP, never down. Variants B and C use this.
                effective_stop = pos.stop_loss
                use_trail = (
                    self.cfg.use_trailing_stop
                    or (self.cfg.use_partial_profit and pos.partial_taken)
                )
                if use_trail and pos.entry_atr > 0:
                    if self.cfg.use_partial_profit and pos.partial_taken:
                        distance_mult = self.cfg.partial_trail_distance_atr_mult
                    else:
                        distance_mult = self.cfg.trailing_distance_atr_mult
                    trigger = (pos.entry_price
                                + self.cfg.trailing_trigger_atr_mult
                                * pos.entry_atr)
                    if pos.best_price >= trigger:
                        trail_stop = (pos.best_price
                                        - distance_mult * pos.entry_atr)
                        effective_stop = max(effective_stop, trail_stop)

                exit_reason = None
                exit_price = None

                # Check SL hit — use min(SL, day_open) to handle gap-throughs
                if day_low <= effective_stop:
                    # 'trailing_stop' distinguishes ratcheted exits from
                    # the original initial stop being hit.
                    exit_reason = ("trailing_stop"
                                    if effective_stop > pos.stop_loss
                                    else "stop_loss")
                    exit_price = min(effective_stop, day_open)

                # Check target hit — unless disabled by the variant.
                elif (not self.cfg.disable_fixed_target
                        and day_high >= pos.target):
                    exit_reason = "target"
                    exit_price = max(pos.target, day_open)

                # Max hold time
                elif pos.days_held >= self.cfg.max_hold_days:
                    exit_reason = "max_hold_days"
                    exit_price = day_close

                # Stale trade: no meaningful profit after N days. Disabled
                # by variants that set stale_trade_days to a large number.
                elif (self.cfg.stale_trade_days > 0
                        and pos.days_held >= self.cfg.stale_trade_days
                        and day_close < pos.entry_price + 1.5 * pos.entry_atr):
                    exit_reason = "stale_trade"
                    exit_price = day_close

                if exit_reason:
                    sell_price = round(exit_price * (1 - self.slippage), 2)
                    charges = self._estimate_charges(pos.qty, pos.entry_price, sell_price)
                    gross_pnl = (sell_price - pos.entry_price) * pos.qty
                    net_pnl = gross_pnl - charges

                    trade = {
                        "symbol": sym,
                        "entry_price": pos.entry_price,
                        "exit_price": sell_price,
                        "qty": pos.qty,
                        "gross_pnl": round(gross_pnl, 2),
                        "charges": round(charges, 2),
                        "pnl": round(net_pnl, 2),
                        "entry_date": pos.entry_date,
                        "exit_date": date,
                        "days_held": pos.days_held,
                        "reason": exit_reason,
                        "sl": pos.stop_loss,
                        "target": pos.target,
                        "atr": pos.entry_atr,
                        "entry_vix_regime": pos.entry_vix_regime,
                        "entry_market_trend": pos.entry_market_trend,
                        "entry_group": pos.entry_group,
                    }
                    if compound:
                        trade["effective_budget"] = round(effective_budget, 2)
                    all_trades.append(trade)
                    day_pnl += net_pnl
                    cumulative_pnl += net_pnl
                    del open_positions[sym]

            # --- Entry checks ---
            # Regime gate: VIX close of T-1 must be below max_vix.
            # No same-bar leak — only data available before `date`.
            entry_blocked_by_vix = self._vix_blocks_entry(date)
            if entry_blocked_by_vix:
                skip_counters["vix_gate"] += 1

            # Phase 4 / addendum §B regime classifier — VIX tiers +
            # Nifty 50/200 SMA trend. Uses T-1 close only (no same-bar leak).
            regime = classify_regime(
                date, self.vix_series, self.nifty_series, self.regime_config,
            )
            regime_log[date] = {
                "vix": regime.vix.value,
                "trend": regime.trend.value,
                "vix_value": regime.vix_value,
                "size_multiplier": regime.size_multiplier,
                "threshold_multiplier": regime.threshold_multiplier,
                "block_all_entries": regime.block_all_entries,
                "blocked_groups": list(regime.blocked_groups),
            }
            if regime.block_all_entries:
                skip_counters["regime_block_all"] += 1

            if (not entry_blocked_by_vix and not regime.block_all_entries
                    and len(open_positions) < self.cfg.max_positions):
                for sym, daily_df in daily_data.items():
                    if sym in open_positions:
                        continue
                    if len(open_positions) >= self.cfg.max_positions:
                        break
                    if date not in daily_df.index:
                        continue
                    # Group-level block (e.g. ELEVATED excludes high_beta_cyclicals)
                    sym_group = self.symbol_to_group.get(sym)
                    if sym_group and sym_group in regime.blocked_groups:
                        skip_counters["regime_block_group"] += 1
                        continue

                    # Need enough history for indicators
                    date_loc = daily_df.index.get_loc(date)
                    lookback = self.cfg.ema_trend + 10
                    if date_loc < lookback:
                        continue

                    # Slice history up to and including today
                    hist = daily_df.iloc[:date_loc + 1].copy()

                    # Parse weekday from date string for day-of-week filter
                    date_weekday = datetime.strptime(date, "%Y-%m-%d").weekday()
                    signal = self.signal_gen.generate_signal(
                        sym, hist, current_weekday=date_weekday
                    )
                    if signal.type != SwingSignalType.BUY:
                        continue

                    atr = signal.atr
                    if atr is None or atr <= 0:
                        continue

                    # Enter at NEXT day's open (signal fires at EOD, execute next morning)
                    if date_loc + 1 < len(daily_df):
                        next_bar = daily_df.iloc[date_loc + 1]
                        entry_price = round(float(next_bar["open"]) * (1 + self.slippage), 2)
                    else:
                        continue  # no next day available

                    sl = round(entry_price - self.cfg.sl_atr_mult * atr, 2)
                    target = round(entry_price + self.cfg.target_atr_mult * atr, 2)

                    # Risk-based position sizing (uses effective_budget if compounding)
                    risk_per_share = self.cfg.sl_atr_mult * atr
                    max_risk = effective_budget * (self.cfg.risk_per_trade_pct / 100.0)
                    qty = int(max_risk / risk_per_share)

                    # Cap by available budget
                    invested = sum(p.entry_price * p.qty for p in open_positions.values())
                    available = effective_budget - invested
                    max_qty_by_budget = int(available / entry_price) if entry_price > 0 else 0
                    qty = min(qty, max_qty_by_budget)

                    # Cap by max_position_pct of effective budget. A single
                    # entry must not deploy more than this fraction.
                    if self.cfg.max_position_pct > 0:
                        cap_value = effective_budget * (self.cfg.max_position_pct / 100.0)
                        max_qty_by_position_pct = (
                            int(cap_value / entry_price) if entry_price > 0 else 0
                        )
                        if qty > max_qty_by_position_pct:
                            qty = max_qty_by_position_pct
                            skip_counters["max_position_pct"] += 1

                    # Phase 4 / addendum §B: VIX ELEVATED shrinks position size.
                    if regime.size_multiplier != 1.0 and qty > 0:
                        qty = max(0, int(qty * regime.size_multiplier))

                    if qty <= 0:
                        continue

                    # Cost-aware quality gate (Phase 2 spec): the planned
                    # target profit must clear round-trip costs by at least
                    # min_profit_cost_multiple (default 3x). Trades that fail
                    # this have negative expected value once realistic
                    # slippage is added back. CostModel is queried for the
                    # exact qty and target so the check scales with size.
                    # In a downtrending market the regime classifier inflates
                    # the multiple by ``downtrend_signal_multiplier`` (Phase 4).
                    effective_min_mult = (
                        self.cfg.min_profit_cost_multiple
                        * regime.threshold_multiplier
                    )
                    # Variants B and C do not have a fixed target — the
                    # minimum profit they aim to lock in is the trailing
                    # trigger (or partial-profit trigger). Use that as the
                    # anchor so the cost gate compares apples to apples.
                    gate_target = target
                    if self.cfg.disable_fixed_target:
                        gate_target = (entry_price
                                        + self.cfg.trailing_trigger_atr_mult
                                        * atr)
                    if not target_clears_costs(
                        qty, entry_price, gate_target, self.cost_model,
                        multiple=effective_min_mult,
                    ):
                        skip_counters["min_profit"] += 1
                        continue

                    pos = SwingPosition(
                        symbol=sym,
                        entry_price=entry_price,
                        qty=qty,
                        stop_loss=sl,
                        target=target,
                        entry_date=date,
                        entry_atr=atr,
                    )
                    # Tag with regime + group for the per-regime / per-group
                    # report breakdowns the walk-forward needs.
                    pos.entry_vix_regime = regime.vix.value
                    pos.entry_market_trend = regime.trend.value
                    pos.entry_group = sym_group or "?"
                    open_positions[sym] = pos
                    logger.info(
                        f"  ENTRY {sym} @ {entry_price:.2f} qty={qty} "
                        f"SL={sl:.2f} TGT={target:.2f} ATR={atr:.2f} "
                        f"regime={regime.vix.value}/{regime.trend.value}"
                        f"{f' budget={effective_budget:.0f}' if compound else ''}"
                    )

            daily_pnl[date] = round(day_pnl, 2)
            if compound:
                budget_history.append((date, round(self.cfg.budget + cumulative_pnl, 2)))

        # Force close any remaining positions at last available price
        effective_budget = self.cfg.budget + cumulative_pnl if compound else self.cfg.budget
        for sym, pos in list(open_positions.items()):
            if sym in daily_data and len(daily_data[sym]) > 0:
                last_close = float(daily_data[sym].iloc[-1]["close"])
            else:
                last_close = pos.entry_price
            sell_price = round(last_close * (1 - self.slippage), 2)
            charges = self._estimate_charges(pos.qty, pos.entry_price, sell_price)
            gross_pnl = (sell_price - pos.entry_price) * pos.qty
            net_pnl = gross_pnl - charges
            trade = {
                "symbol": sym,
                "entry_price": pos.entry_price,
                "exit_price": sell_price,
                "qty": pos.qty,
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "pnl": round(net_pnl, 2),
                "entry_date": pos.entry_date,
                "exit_date": all_dates[-1] if all_dates else "N/A",
                "days_held": pos.days_held,
                "reason": "backtest_end",
                "sl": pos.stop_loss,
                "target": pos.target,
                "atr": pos.entry_atr,
            }
            all_trades.append(trade)
            cumulative_pnl += net_pnl
            last_date = all_dates[-1] if all_dates else "N/A"
            daily_pnl[last_date] = daily_pnl.get(last_date, 0.0) + net_pnl

        report = self._compute_report(
            all_trades, daily_pnl, daily_invested, self.cfg.budget,
        )
        report.skip_counters = dict(skip_counters)
        report.regime_log = regime_log
        if compound:
            report.budget_history = budget_history
            report.final_effective_budget = round(self.cfg.budget + cumulative_pnl, 2)
        return report

    # ------------------------------------------------------------------
    # Report computation (reuses BacktestReport from engine_backtester)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_report(trades: List[Dict[str, Any]],
                        daily_pnl: Dict[str, float],
                        daily_invested: Optional[Dict[str, float]] = None,
                        starting_capital: float = 0.0) -> BacktestReport:
        """Build the BacktestReport.

        Sharpe is computed on daily *returns* (P&L / starting_capital) and
        annualized by sqrt(252). Drawdown is reported both in absolute INR
        and as a fraction of starting_capital. CAGR uses the number of
        trading days / 252.
        """
        report = BacktestReport()
        report.trade_log = trades
        report.daily_pnl = daily_pnl
        report.total_trades = len(trades)
        report.starting_capital = float(starting_capital)

        if not trades:
            return report

        pnls = [t["pnl"] for t in trades]
        report.total_pnl = round(sum(pnls), 2)
        report.gross_pnl = round(sum(t.get("gross_pnl", 0.0) for t in trades), 2)
        report.total_charges = round(sum(t.get("charges", 0.0) for t in trades), 2)
        report.winning_trades = sum(1 for p in pnls if p > 0)
        report.losing_trades = sum(1 for p in pnls if p <= 0)
        report.win_rate = report.winning_trades / len(pnls)

        # Profit factor
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        report.profit_factor = round(gp / gl, 4) if gl > 0 else float("inf")

        # Max drawdown (peak-to-trough on equity curve)
        equity = peak = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        report.max_drawdown = round(max_dd, 2)
        if starting_capital > 0:
            report.max_drawdown_pct = round(max_dd / starting_capital, 6)

        # Sharpe ratio on daily RETURNS (not raw INR P&L) to make the metric
        # comparable across capital sizes.
        dr_pnls = list(daily_pnl.values())
        if len(dr_pnls) > 1 and starting_capital > 0:
            returns = [p / starting_capital for p in dr_pnls]
            mean_r = sum(returns) / len(returns)
            var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std = math.sqrt(var) if var > 0 else 1e-12
            report.sharpe_ratio = round((mean_r / std) * math.sqrt(252), 4)

        # CAGR — assumes the backtest spans `len(daily_pnl)` trading days.
        if starting_capital > 0 and len(daily_pnl) > 1:
            final_equity = starting_capital + report.total_pnl
            years = len(daily_pnl) / 252.0
            if final_equity > 0 and years > 0:
                report.cagr = round(
                    (final_equity / starting_capital) ** (1.0 / years) - 1.0, 6
                )

        # Average holding days
        holds = [t.get("days_held", 0) for t in trades]
        if holds:
            report.avg_holding_days = round(sum(holds) / len(holds), 2)

        # Exposure %: average fraction of starting_capital that was deployed.
        if daily_invested and starting_capital > 0:
            invested_vals = [v for v in daily_invested.values() if v >= 0]
            if invested_vals:
                report.exposure_pct = round(
                    sum(invested_vals) / (len(invested_vals) * starting_capital), 6
                )

        # Per-symbol breakdown
        by_sym: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            sym = t.get("symbol", "?")
            d = by_sym.setdefault(sym, {"trades": 0, "pnl": 0.0, "wins": 0})
            d["trades"] += 1
            d["pnl"] += t.get("pnl", 0.0)
            if t.get("pnl", 0.0) > 0:
                d["wins"] += 1
        for sym, d in by_sym.items():
            d["pnl"] = round(d["pnl"], 2)
            d["win_rate"] = round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0
        report.per_symbol = by_sym

        # Phase 4 / addendum §D — per-group, per-VIX-regime, per-trend.
        def _bucket(key_fn):
            buckets: Dict[str, Dict[str, Any]] = {}
            for t in trades:
                k = str(key_fn(t))
                d = buckets.setdefault(k, {"trades": 0, "pnl": 0.0, "wins": 0})
                d["trades"] += 1
                d["pnl"] += t.get("pnl", 0.0)
                if t.get("pnl", 0.0) > 0:
                    d["wins"] += 1
            for d in buckets.values():
                d["pnl"] = round(d["pnl"], 2)
                d["win_rate"] = round(d["wins"] / d["trades"], 4) if d["trades"] else 0.0
            return buckets

        report.per_group = _bucket(lambda t: t.get("entry_group", "?"))
        report.per_vix_regime = _bucket(lambda t: t.get("entry_vix_regime", "?"))
        report.per_market_trend = _bucket(lambda t: t.get("entry_market_trend", "?"))

        return report

    # ------------------------------------------------------------------
    # Enhanced summary for swing trades
    # ------------------------------------------------------------------

    @staticmethod
    def print_swing_summary(report: BacktestReport, config: SwingConfig,
                            compound: bool = False) -> None:
        """Print a detailed swing-specific summary."""
        print("=" * 70)
        mode_label = "COMPOUND REINVESTMENT" if compound else "FIXED BUDGET"
        print(f"SWING BACKTEST RESULTS ({mode_label})")
        print("=" * 70)
        print(f"  Base Budget      : Rs.{config.budget:,.0f}")
        if compound and hasattr(report, "final_effective_budget"):
            print(f"  Final Budget     : Rs.{report.final_effective_budget:,.0f}")
            growth = report.final_effective_budget - config.budget
            growth_pct = growth / config.budget * 100
            print(f"  Budget Growth    : Rs.{growth:+,.0f} ({growth_pct:+.2f}%)")
        print(f"  Max positions    : {config.max_positions}")
        print(f"  Risk/trade       : {config.risk_per_trade_pct}%")
        print(f"  SL multiplier    : {config.sl_atr_mult} ATR")
        print(f"  Target multiplier: {config.target_atr_mult} ATR")
        print(f"  Max hold days    : {config.max_hold_days}")
        print("-" * 70)
        print(f"  Total P&L        : Rs.{report.total_pnl:+,.2f}")
        print(f"  Total Trades     : {report.total_trades}")
        print(f"  Win / Loss       : {report.winning_trades} / {report.losing_trades}")
        print(f"  Win Rate         : {report.win_rate:.1%}")
        print(f"  Max Drawdown     : Rs.{report.max_drawdown:,.2f}")
        print(f"  Sharpe Ratio     : {report.sharpe_ratio:.2f}")
        print(f"  Profit Factor    : {report.profit_factor:.2f}")

        if report.trade_log:
            total_charges = sum(t.get("charges", 0) for t in report.trade_log)
            total_gross = sum(t.get("gross_pnl", 0) for t in report.trade_log)
            avg_hold = sum(t.get("days_held", 0) for t in report.trade_log) / len(report.trade_log)
            charge_pct = (total_charges / total_gross * 100) if total_gross > 0 else 0

            print(f"  Total Charges    : Rs.{total_charges:,.2f}")
            print(f"  Gross Profit     : Rs.{total_gross:+,.2f}")
            print(f"  Charge % of Gross: {charge_pct:.1f}%")
            print(f"  Avg Hold Days    : {avg_hold:.1f}")

            # Exit reason breakdown
            reasons = {}
            for t in report.trade_log:
                r = t.get("reason", "unknown")
                reasons[r] = reasons.get(r, 0) + 1
            print(f"  Exit Reasons     : {reasons}")

        print("-" * 70)
        if report.trade_log:
            print("\n  TRADE LOG:")
            print(f"  {'Symbol':<12} {'Entry':>8} {'Exit':>8} {'Qty':>4} "
                  f"{'Gross':>8} {'Chrg':>6} {'Net':>8} {'Days':>4} {'Reason':<15} {'Entry Date'}")
            print("  " + "-" * 100)
            for t in report.trade_log:
                print(f"  {t['symbol']:<12} {t['entry_price']:>8.2f} {t['exit_price']:>8.2f} "
                      f"{t['qty']:>4} {t.get('gross_pnl', 0):>+8.2f} {t.get('charges', 0):>6.2f} "
                      f"{t['pnl']:>+8.2f} {t.get('days_held', 0):>4} "
                      f"{t.get('reason', ''):<15} {t.get('entry_date', '')}")
        print("=" * 70)
