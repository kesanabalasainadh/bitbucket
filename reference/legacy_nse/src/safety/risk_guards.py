
# risk_guards.py
"""
Production-grade risk guardrails for the Upstox trading bot.

Exposes:
- RiskConfig: dataclass for all tunables with sane env-backed defaults
- RiskState:  lightweight runtime tracker (cooldowns, last trades)
- RiskGuards: orchestrator with .allowed_to_trade() and granular checks
- risk_budget_exceeded(price, budget, risk_budget_pct) -> bool
- check_daily_trade_limit(today_trade_count: int|None = None, max_trades: int|None = None) -> bool
- check_daily_loss_limit(max_loss: float|None = None) -> bool

This module is designed to be imported by strategy_watch.py like:

    from risk_guards import (
        RiskConfig, RiskState, RiskGuards, risk_budget_exceeded
    )
    # and optionally:
    from risk_guards import check_daily_trade_limit, check_daily_loss_limit

KEY POINTS
- Market hours are NSE IST 09:15–15:30 when market_hours_only=True
- Cooldown is enforced per symbol (and optional global)
- Daily loss cap computed from env BUDGET & MAX_DAILY_LOSS_PCT if not provided
- “Fail-safe” philosophy: on uncertainty, block trading
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, Optional, Tuple

# db_logger is expected to be part of the repo:
# - get_today_pnl() -> float
# - get_today_trade_count() -> int
_DB_LOGGER_AVAILABLE = False
try:
    from src.data.db_logger import get_today_pnl, get_today_trade_count
    _DB_LOGGER_AVAILABLE = True
except Exception as _db_err:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        f"db_logger import failed: {_db_err} — risk guards will BLOCK trading (fail-safe)"
    )
    # Fail-safe stubs: raise so callers' except blocks trigger blocking behavior
    def get_today_pnl() -> float:
        raise RuntimeError("db_logger unavailable — cannot determine today's PnL")
    def get_today_trade_count() -> int:
        raise RuntimeError("db_logger unavailable — cannot determine today's trade count")

# ---------- Timezone helpers (IST market hours) ----------
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    # Fallback to fixed offset IST (UTC+5:30) if ZoneInfo unavailable
    class _FixedIST(timezone):
        def __new__(cls):
            return timezone(timedelta(hours=5, minutes=30))
    IST = _FixedIST()

NSE_OPEN_IST = dt_time(9, 15)
NSE_CLOSE_IST = dt_time(15, 30)


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def is_market_open_ist(now: Optional[datetime] = None) -> bool:
    """True only during NSE market hours (Mon–Fri 09:15–15:30 IST)."""
    now = now or _now_ist()
    if now.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    t = now.timetz()
    return (t >= NSE_OPEN_IST and t < NSE_CLOSE_IST)


# ---------- Config dataclass ----------
def _env_bool(key: str, default: bool) -> bool:
    return (os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "y"))


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except Exception:
        return default


# ---------- Hard ceilings ----------
# Live mode REFUSES to start if any of these is loosened in config.
# The hard ceilings encode the worst risk profile we ever accept on a
# personal account running a self-developed swing system on the
# SEBI Generic Algo ID tier (< 10 orders/sec).
HARD_CEILING_MAX_TRADES_PER_DAY: int = 10
HARD_CEILING_MAX_DAILY_LOSS_PCT: float = 5.0       # never lose more than 5% of budget in one day
HARD_CEILING_MAX_BUYS_PER_SYMBOL: int = 2
HARD_CEILING_MAX_OPEN_POSITIONS: int = 10
HARD_CEILING_MAX_POSITION_PCT: float = 40.0        # never put more than 40% of budget in one symbol
HARD_CEILING_RISK_BUDGET_PCT: float = 0.50         # never let one entry consume > 50% of risk slice
HARD_FLOOR_MIN_PROFIT_COST_MULTIPLE: float = 2.0   # target must clear 2x costs at minimum


class RiskConfigError(RuntimeError):
    """Raised when live mode is attempted with loose or missing risk limits."""


@dataclass
class RiskConfig:
    # Core knobs used by strategy_watch constructor
    budget: float = _env_float("BUDGET", 1000.0)
    stop_loss_pct: float = _env_float("STOP_LOSS_PCT", 2.0)             # 2% default
    price_cap: float = _env_float("PRICE_CAP", 0.0)                     # 0 => no cap
    cooldown_s: float = _env_float("COOLDOWN_S", 5.0)
    market_hours_only: bool = _env_bool("MARKET_HOURS_ONLY", True)

    # Extended risk knobs (env-backed). Conservative swing defaults.
    risk_budget_pct: float = _env_float("RISK_BUDGET_PCT", 0.10)        # 10% of budget
    max_trades_per_day: int = _env_int("MAX_TRADES_PER_DAY", 5)         # was 100
    max_buys_per_symbol: int = _env_int("MAX_BUYS_PER_SYMBOL", 1)       # was 3
    max_open_positions: int = _env_int("MAX_OPEN_POSITIONS", 5)         # NEW
    max_position_pct: float = _env_float("MAX_POSITION_PCT", 20.0)      # NEW: 20% of budget per symbol

    daily_profit_target_pct: float = _env_float("DAILY_PROFIT_TARGET_PCT", 0.0)
    max_daily_loss_pct: float = _env_float("MAX_DAILY_LOSS_PCT", 2.5)   # was 10.0

    halt_after_profit: bool = _env_bool("HALT_AFTER_PROFIT", False)
    halt_after_loss: bool = _env_bool("HALT_AFTER_LOSS", True)

    # Optional global cooldown (blocks ANY new trade for X seconds)
    global_cooldown_s: float = _env_float("GLOBAL_COOLDOWN_S", 0.0)

    # Slippage guardrails (optional; informational here)
    slippage_pct: float = _env_float("SLIPPAGE_PCT", 0.05)

    # Misc buy/sell gating toggles (keep simple here; strategies can add more)
    block_above_price_cap: bool = True
    block_when_pnl_unknown: bool = True
    block_when_trades_unknown: bool = True

    # Safety: minimum expected risk-reward or absolute net profit required (strategy can pass)
    min_rr: float = _env_float("MIN_RR", 0.0)
    min_net_profit: float = _env_float("MIN_NET_PROFIT", 0.0)

    # Cost-aware position-quality gate: profit at target must clear at least
    # this multiple of the round-trip transaction cost computed by CostModel.
    # A target that doesn't pay its own costs 3x has negative expected value
    # after realistic slippage. Phase 2 spec.
    min_profit_cost_multiple: float = _env_float("MIN_PROFIT_COST_MULTIPLE", 3.0)

    # Circuit breaker: block BUY if stock drops > X% from day's first tick
    circuit_breaker_pct: float = _env_float("CIRCUIT_BREAKER_PCT", 5.0)  # 5% drop
    # Price band: reject prices outside [min_price, max_price]
    min_price: float = _env_float("MIN_PRICE", 1.0)   # below ₹1 = illiquid
    max_price: float = _env_float("MAX_PRICE", 50000.0)  # above 50K = too expensive

    # ------------------------------------------------------------------
    # Live-mode safety validation
    # ------------------------------------------------------------------
    def validate_live(self) -> None:
        """Refuse live mode unless every safety limit is set and at or below
        its hard ceiling. Raises ``RiskConfigError`` with the offending field
        listed. Called on engine startup whenever ``mode == 'live'``.

        Design intent: a misconfiguration ("MAX_TRADES_PER_DAY=1000") must
        crash the launcher rather than silently let the engine place 1000
        orders. Hard ceilings encode "never under any config can the system
        do worse than this".
        """
        problems = []

        if self.budget is None or self.budget <= 0:
            problems.append("budget must be > 0")
        if self.max_trades_per_day is None or self.max_trades_per_day <= 0:
            problems.append("max_trades_per_day must be > 0")
        elif self.max_trades_per_day > HARD_CEILING_MAX_TRADES_PER_DAY:
            problems.append(
                f"max_trades_per_day={self.max_trades_per_day} exceeds hard ceiling "
                f"{HARD_CEILING_MAX_TRADES_PER_DAY}"
            )

        if self.max_daily_loss_pct is None or self.max_daily_loss_pct <= 0:
            problems.append("max_daily_loss_pct must be > 0")
        elif self.max_daily_loss_pct > HARD_CEILING_MAX_DAILY_LOSS_PCT:
            problems.append(
                f"max_daily_loss_pct={self.max_daily_loss_pct} exceeds hard ceiling "
                f"{HARD_CEILING_MAX_DAILY_LOSS_PCT}"
            )

        if self.max_buys_per_symbol is None or self.max_buys_per_symbol <= 0:
            problems.append("max_buys_per_symbol must be > 0")
        elif self.max_buys_per_symbol > HARD_CEILING_MAX_BUYS_PER_SYMBOL:
            problems.append(
                f"max_buys_per_symbol={self.max_buys_per_symbol} exceeds hard ceiling "
                f"{HARD_CEILING_MAX_BUYS_PER_SYMBOL}"
            )

        if self.max_open_positions is None or self.max_open_positions <= 0:
            problems.append("max_open_positions must be > 0")
        elif self.max_open_positions > HARD_CEILING_MAX_OPEN_POSITIONS:
            problems.append(
                f"max_open_positions={self.max_open_positions} exceeds hard ceiling "
                f"{HARD_CEILING_MAX_OPEN_POSITIONS}"
            )

        if self.max_position_pct is None or self.max_position_pct <= 0:
            problems.append("max_position_pct must be > 0")
        elif self.max_position_pct > HARD_CEILING_MAX_POSITION_PCT:
            problems.append(
                f"max_position_pct={self.max_position_pct} exceeds hard ceiling "
                f"{HARD_CEILING_MAX_POSITION_PCT}"
            )

        if self.risk_budget_pct is None or self.risk_budget_pct <= 0:
            problems.append("risk_budget_pct must be > 0")
        elif self.risk_budget_pct > HARD_CEILING_RISK_BUDGET_PCT:
            problems.append(
                f"risk_budget_pct={self.risk_budget_pct} exceeds hard ceiling "
                f"{HARD_CEILING_RISK_BUDGET_PCT}"
            )

        if self.min_profit_cost_multiple is None or \
                self.min_profit_cost_multiple < HARD_FLOOR_MIN_PROFIT_COST_MULTIPLE:
            problems.append(
                f"min_profit_cost_multiple={self.min_profit_cost_multiple} below hard floor "
                f"{HARD_FLOOR_MIN_PROFIT_COST_MULTIPLE}"
            )

        # SEBI compliance: live mode requires registered algo name + static IP.
        if not os.environ.get("ALGO_NAME", "").strip():
            problems.append(
                "ALGO_NAME env var is empty — required for SEBI-compliant order "
                "placement on the Generic Algo ID tier"
            )
        if not os.environ.get("REGISTERED_STATIC_IP", "").strip():
            problems.append(
                "REGISTERED_STATIC_IP env var is empty — required for the SEBI "
                "static-IP check on live-mode startup"
            )

        if problems:
            raise RiskConfigError(
                "Live-mode risk configuration rejected:\n  - " +
                "\n  - ".join(problems) +
                "\nFix .env / config and restart. Hard ceilings are in "
                "src/safety/risk_guards.py."
            )


@dataclass
class RiskState:
    """
    Runtime state holder. Strategy can keep one instance for the session.
    """
    # per-symbol last trade (epoch seconds)
    last_trade_ts: Dict[str, float] = field(default_factory=dict)
    # per-symbol buy counters for the current day
    buys_today: Dict[str, int] = field(default_factory=dict)
    # global last trade time for optional global cooldown
    last_global_trade_ts: float = 0.0
    # day marker to reset buys_today/counters at midnight IST
    day_ist: str = field(default_factory=lambda: _now_ist().strftime("%Y-%m-%d"))
    # circuit breaker: first tick price per symbol for the day
    day_open_price: Dict[str, float] = field(default_factory=dict)

    def _maybe_rollover(self) -> None:
        today = _now_ist().strftime("%Y-%m-%d")
        if today != self.day_ist:
            self.day_ist = today
            self.buys_today.clear()
            self.last_trade_ts.clear()
            self.day_open_price.clear()


# ---------- Standalone helpers expected elsewhere ----------
def risk_budget_exceeded(price: float,
                         budget: Optional[float] = None,
                         risk_budget_pct: Optional[float] = None) -> bool:
    """
    True if not enough budget (or risk slice) to afford at least 1 share.
    """
    budget = budget if budget is not None else _env_float("BUDGET", 1000.0)
    rbp = risk_budget_pct if risk_budget_pct is not None else _env_float("RISK_BUDGET_PCT", 0.10)
    if price is None or price <= 0:
        return True
    # Risk slice to deploy on a single entry
    slice_amt = max(1.0, budget * rbp)
    return price > slice_amt


def check_daily_trade_limit(today_trade_count: Optional[int] = None,
                            max_trades: Optional[int] = None) -> bool:
    """
    Returns True if under the daily trade cap.
    If counters are unknown and block_when_trades_unknown is in effect at call sites,
    strategy should decide to block.
    """
    try:
        if today_trade_count is None:
            today_trade_count = int(get_today_trade_count())
        if max_trades is None:
            max_trades = _env_int("MAX_TRADES_PER_DAY", 100)
    except Exception:
        # Can't compute -> let the caller decide; default to False to be safe
        return False
    return int(today_trade_count) < int(max_trades)


def check_daily_loss_limit(max_loss: Optional[float] = None) -> bool:
    """
    Return True if it's OK to continue trading today (i.e., daily loss NOT exceeded).

    If max_loss is None, compute it from:
        max_loss = -abs(BUDGET) * (MAX_DAILY_LOSS_PCT / 100.0)
    """
    try:
        pnl = float(get_today_pnl() or 0.0)
    except Exception:
        # Unknown P&L -> fail-safe block
        return False

    if max_loss is None:
        budget = _env_float("BUDGET", 1000.0)
        max_daily_loss_pct = _env_float("MAX_DAILY_LOSS_PCT", 10.0)
        max_loss = -abs(budget) * (abs(max_daily_loss_pct) / 100.0)

    return pnl > max_loss  # trading allowed only while P&L above the negative cap


# ---------- Orchestrator ----------
class RiskGuards:

    """
    Centralized risk enforcement. Instantiate once per session:

        cfg = RiskConfig(...)
        state = RiskState()
        guards = RiskGuards(cfg, state)

    Use .allowed_to_trade(symbol, side, price, *, now=None, reason_out=True)
         -> (bool_allowed, reason_string)
    """

    def __init__(self, cfg: RiskConfig, state: Optional[RiskState] = None):
        self.cfg = cfg
        self.state = state or RiskState()

    # ---- public API ----
    def allowed_to_trade(
        self,
        symbol: str,
        side: str,
        price: Optional[float],
        *,
        now: Optional[datetime] = None,
        reason_out: bool = True,
        today_trade_count: Optional[int] = None,
        today_pnl: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Composite gate. Returns (allowed, reason).

        Order of checks (early exits on block):
          1) Market hours (if enabled)
          2) Daily loss cap (and halt-after-loss, if configured)
          3) Daily profit target (and halt-after-profit, if configured)
          4) Daily trade count cap
          5) Global cooldown
          6) Per-symbol cooldown
          7) Basic price / budget slice sanity
          8) Per-symbol buys count (only for BUY side)

        Note: This function is intentionally conservative; any failure returns False.
        """
        # Day rollover housekeeping
        self.state._maybe_rollover()

        # 1) Market hours
        if self.cfg.market_hours_only:
            if not is_market_open_ist(now):
                return self._deny("Market closed (NSE 09:15–15:30 IST).", reason_out)

        # 2) Daily loss cap
        if not self._daily_loss_ok(today_pnl):
            return self._deny("Daily loss limit breached.", reason_out)

        # 3) Profit target & halts
        ok, why = self._daily_profit_ok(today_pnl)
        if not ok:
            return self._deny(why, reason_out)

        # 4) Trades per day cap
        if not self._trades_today_ok(today_trade_count):
            return self._deny("Daily trade cap reached.", reason_out)

        # 5) Global cooldown
        if self.cfg.global_cooldown_s > 0:
            if not self._global_cooldown_ok():
                return self._deny(f"Global cooldown {self.cfg.global_cooldown_s:.0f}s.", reason_out)

        # 6) Per-symbol cooldown
        if not self._symbol_cooldown_ok(symbol):
            return self._deny(f"{symbol} cooldown {self.cfg.cooldown_s:.0f}s.", reason_out)

        # 7) Price / budget checks
        if price is None or price <= 0:
            return self._deny("Invalid/missing price.", reason_out)
        if price < self.cfg.min_price:
            return self._deny(f"Price {price:.2f} below min band {self.cfg.min_price}.", reason_out)
        if self.cfg.max_price > 0 and price > self.cfg.max_price:
            return self._deny(f"Price {price:.2f} above max band {self.cfg.max_price}.", reason_out)
        if self.cfg.block_above_price_cap and self.cfg.price_cap > 0 and price > self.cfg.price_cap:
            return self._deny(f"Price {price} exceeds cap {self.cfg.price_cap}.", reason_out)
        if risk_budget_exceeded(price, self.cfg.budget, self.cfg.risk_budget_pct):
            return self._deny(f"Risk slice insufficient for ₹{price:.2f}.", reason_out)

        # 8) Circuit breaker: block BUY if stock dropped > X% from day open
        if side.upper() == "BUY" and self.cfg.circuit_breaker_pct > 0:
            open_px = self.state.day_open_price.get(symbol)
            if open_px and open_px > 0:
                drop_pct = (open_px - price) / open_px * 100.0
                if drop_pct >= self.cfg.circuit_breaker_pct:
                    return self._deny(
                        f"Circuit breaker: {symbol} dropped {drop_pct:.1f}% from open "
                        f"({open_px:.2f}→{price:.2f}), threshold={self.cfg.circuit_breaker_pct}%.",
                        reason_out)

        # 9) Per-symbol buy throttling (BUY only)
        if side.upper() == "BUY":
            if not self._buys_per_symbol_ok(symbol):
                return self._deny(f"{symbol} max buys reached ({self.cfg.max_buys_per_symbol}).", reason_out)

        # All green
        return True, "OK"

    def record_tick(self, symbol: str, price: float) -> None:
        """Record first tick of day for circuit breaker reference."""
        self.state._maybe_rollover()
        if symbol not in self.state.day_open_price and price > 0:
            self.state.day_open_price[symbol] = price

    def record_trade(self, symbol: str, side: str) -> None:
        """
        Call this immediately after a trade is placed (filled or accepted).
        Updates cooldown timers and per-symbol counters.
        """
        now_ts = time.time()
        self.state.last_trade_ts[symbol] = now_ts
        self.state.last_global_trade_ts = now_ts
        # Increment per-symbol buys counter on BUY
        if str(side).upper() == "BUY":
            self.state.buys_today[symbol] = self.state.buys_today.get(symbol, 0) + 1

    def daily_loss_exceeded(self, today_pnl: Optional[float] = None, max_loss: Optional[float] = None) -> bool:
        """
        True if today's realized P&L is at or below the daily loss floor.
        """
        try:
            pnl = float(today_pnl if today_pnl is not None else get_today_pnl() or 0.0)
        except Exception:
            return True  # fail-safe: treat as exceeded
        if max_loss is None:
            budget = self.cfg.budget
            max_loss = -abs(budget) * (abs(self.cfg.max_daily_loss_pct) / 100.0)
        return pnl <= max_loss

    def daily_profit_reached(self, today_pnl: Optional[float] = None) -> bool:
        """
        True if today's profit target (pct of budget) is reached.
        0% target means disabled.
        """
        if self.cfg.daily_profit_target_pct <= 0:
            return False
        try:
            pnl = float(today_pnl if today_pnl is not None else get_today_pnl() or 0.0)
        except Exception:
            return False  # be lenient on profit target
        target = abs(self.cfg.budget) * (abs(self.cfg.daily_profit_target_pct) / 100.0)
        return pnl >= target

    def trades_cap_reached(self, today_trade_count: Optional[int] = None) -> bool:
        """
        True if daily trade count has reached/exceeded max_trades_per_day.
        """
        try:
            cnt = int(today_trade_count if today_trade_count is not None else get_today_trade_count())
        except Exception:
            return True  # fail-safe
        return cnt >= int(self.cfg.max_trades_per_day)

    def symbol_in_cooldown(self, symbol: str) -> bool:
        last = self.state.last_trade_ts.get(symbol)
        if last is None:
            return False
        return (time.time() - last) < float(self.cfg.cooldown_s)

    def global_in_cooldown(self) -> bool:
        if self.cfg.global_cooldown_s <= 0:
            return False
        last = self.state.last_global_trade_ts or 0.0
        return (time.time() - last) < float(self.cfg.global_cooldown_s)
    # --- compatibility shims for older strategy code ---
    def allow_budget(self, price: float, qty: int = 1):
        """
        Older strategies call this before placing a BUY.
        Returns (ok, reason). We keep the same slice logic used elsewhere.
        """
        try:
            px = float(price)
        except Exception:
            return False, "Invalid/missing price."

        if px <= 0:
            return False, "Invalid/missing price."
        # keep parity with existing checks: slice is on unit price, not qty*price
        if risk_budget_exceeded(px, self.cfg.budget, self.cfg.risk_budget_pct):
            return False, f"Risk slice insufficient for ₹{px:.2f}."
        return True, "OK"

    def allow_price_cap(self, price: float):
        """
        Older strategies call this after allow_budget.
        Returns (ok, reason).
        """
        try:
            px = float(price)
        except Exception:
            return False, "Invalid/missing price."

        if px <= 0:
            return False, "Invalid/missing price."
        if self.cfg.block_above_price_cap and self.cfg.price_cap > 0 and px > self.cfg.price_cap:
            return False, f"Price {px:.2f} exceeds cap {self.cfg.price_cap:.2f}."
        return True, "OK"

    # ---- private helpers ----
    def _deny(self, msg: str, reason_out: bool) -> Tuple[bool, str]:
        return (False, msg if reason_out else "")

    def _daily_loss_ok(self, today_pnl: Optional[float]) -> bool:
        if self.daily_loss_exceeded(today_pnl):
            return not self.cfg.halt_after_loss  # if halt_after_loss True → block
        return True

    def _daily_profit_ok(self, today_pnl: Optional[float]) -> Tuple[bool, str]:
        """
        Returns (ok, reason_if_blocked)
        """
        if self.daily_profit_reached(today_pnl):
            if self.cfg.halt_after_profit:
                return False, "Daily profit target reached; halting."
            # Allowed but informational
            return True, "Profit target reached; continuing (halt disabled)."
        return True, "OK"

    def _trades_today_ok(self, today_trade_count: Optional[int]) -> bool:
        return not self.trades_cap_reached(today_trade_count)

    def _symbol_cooldown_ok(self, symbol: str) -> bool:
        return not self.symbol_in_cooldown(symbol)

    def _global_cooldown_ok(self) -> bool:
        return not self.global_in_cooldown()

    def _buys_per_symbol_ok(self, symbol: str) -> bool:
        maxb = int(self.cfg.max_buys_per_symbol)
        if maxb == 0:
            return False
        if maxb < 0:
            return True
        # Use max of memory count and DB count to avoid double-counting
        # (both track the same trades from different sources)
        mem_count = int(self.state.buys_today.get(symbol, 0))
        db_count = 0
        try:
            from src.data.db_logger import count_symbol_buys_today
            db_count = int(count_symbol_buys_today(symbol) or 0)
        except Exception:
            pass
        return max(mem_count, db_count) < maxb

    def allow_market_session(self):
        now = _now_ist()
        open_now = is_market_open_ist(now)
        if not open_now and self.cfg.market_hours_only:
            return False, "market closed"
        return True, "ok"

    def target_clears_costs(self, qty: int, entry_price: float,
                            target_price: float, cost_model) -> Tuple[bool, str]:
        """Return (ok, reason) using the configured min_profit_cost_multiple.

        Wraps ``src.backtest.cost_model.target_clears_costs`` so callers
        don't need to import both modules. ``cost_model`` is any object
        exposing ``.total(qty, entry, sell)`` — typically the CostModel
        dataclass.
        """
        # Local import to avoid a circular dep if cost_model ever imports risk.
        from src.backtest.cost_model import target_clears_costs as _tcc

        if qty <= 0 or entry_price <= 0 or target_price <= entry_price:
            return False, (
                f"target ({target_price:.2f}) must be > entry ({entry_price:.2f}) "
                f"with qty > 0"
            )
        ok = _tcc(qty, entry_price, target_price, cost_model,
                  multiple=self.cfg.min_profit_cost_multiple)
        if ok:
            return True, "OK"
        profit_potential = (target_price - entry_price) * qty
        cost = cost_model.total(qty, entry_price, target_price)
        ratio = profit_potential / cost if cost > 0 else float("inf")
        return False, (
            f"target profit Rs {profit_potential:.2f} clears costs Rs {cost:.2f} "
            f"only {ratio:.2f}x (need {self.cfg.min_profit_cost_multiple:.1f}x)"
        )


# ---------- Backwards-compatible aliases (some code may import these) ----------
def daily_loss_exceeded(max_loss: Optional[float] = None) -> bool:
    """
    Legacy helper: True if daily loss exceeded. Reads P&L from db_logger.
    """
    try:
        pnl = float(get_today_pnl() or 0.0)
    except Exception:
        return True
    if max_loss is None:
        budget = _env_float("BUDGET", 1000.0)
        max_loss = -abs(budget) * (abs(_env_float("MAX_DAILY_LOSS_PCT", 10.0)) / 100.0)
    return pnl <= max_loss


# Keep simple boolean wrappers expected by older strategy code:
def allowed_to_trade_today() -> bool:
    """Deprecated: prefer RiskGuards.allowed_to_trade(...)."""
    return check_daily_loss_limit() and check_daily_trade_limit()


# --------- Module import surface that strategy_watch expects ----------
__all__ = [
    "RiskConfig",
    "RiskConfigError",
    "RiskState",
    "RiskGuards",
    "risk_budget_exceeded",
    "check_daily_trade_limit",
    "check_daily_loss_limit",
    "is_market_open_ist",
    "HARD_CEILING_MAX_TRADES_PER_DAY",
    "HARD_CEILING_MAX_DAILY_LOSS_PCT",
    "HARD_CEILING_MAX_BUYS_PER_SYMBOL",
    "HARD_CEILING_MAX_OPEN_POSITIONS",
    "HARD_CEILING_MAX_POSITION_PCT",
    "HARD_CEILING_RISK_BUDGET_PCT",
    "HARD_FLOOR_MIN_PROFIT_COST_MULTIPLE",
]

# ===== Back-compat shims for strategy_watch =====
# Consolidated shim definitions (no duplicates).

def _ensure_positions_dict(state):
    if not hasattr(state, "positions") or not isinstance(getattr(state, "positions", None), dict):
        state.positions = {}


def _shim_open_position(self, symbol: str, entry: float, qty: int):
    """Track an opened position in in-memory state."""
    _ensure_positions_dict(self.state)
    self.state.positions[symbol] = {
        "entry": float(entry),
        "qty": int(qty),
        "ts": time.time(),
    }


def _shim_close_position(self, symbol: str):
    """Remove a position from state (after SELL/exit)."""
    _ensure_positions_dict(self.state)
    self.state.positions.pop(symbol, None)


def _shim_mark_order(self, symbol=None, side=None, ts=None, note=None):
    """
    Called by strategy_watch.mark(...). Stamps last trade times so
    cooldowns & bookkeeping keep working.
    """
    try:
        t = float(ts) if ts is not None else time.time()
    except Exception:
        t = time.time()
    if hasattr(self.state, "last_global_trade_ts"):
        self.state.last_global_trade_ts = t
    if symbol:
        if not hasattr(self.state, "last_trade_ts") or not isinstance(self.state.last_trade_ts, dict):
            self.state.last_trade_ts = {}
        self.state.last_trade_ts[symbol] = t
        if str(side).upper() == "BUY":
            self.state.buys_today[symbol] = self.state.buys_today.get(symbol, 0) + 1


def _shim_stop_loss_hit(self, symbol: str, ltp: float):
    """
    Legacy check used by some watchers.
    Returns (hit: bool, reason: str)
    """
    try:
        pct = float(getattr(self.cfg, "stop_loss_pct", 0.0) or 0.0)
    except Exception:
        pct = 0.0
    if pct <= 0:
        return False, "SL disabled"

    _ensure_positions_dict(self.state)
    pos = self.state.positions.get(symbol)
    if not pos:
        return False, "no position"

    entry = pos.get("entry") or pos.get("avg") or pos.get("price")
    if not entry or ltp is None or ltp <= 0:
        return False, "missing entry/ltp"

    sl_price = float(entry) * (1.0 - abs(pct) / 100.0)
    if ltp <= sl_price:
        return True, f"SL hit {ltp:.2f} <= {sl_price:.2f}"
    return False, "OK"


# Attach shims only if missing on the class:
try:
    _shims = {
        "open_position": _shim_open_position,
        "close_position": _shim_close_position,
        "mark_order": _shim_mark_order,
        "stop_loss_hit": _shim_stop_loss_hit,
    }
    for _name, _fn in _shims.items():
        if not hasattr(RiskGuards, _name):
            setattr(RiskGuards, _name, _fn)
except Exception as _e:
    print("[WARN] risk_guards shim attach failed:", _e)
