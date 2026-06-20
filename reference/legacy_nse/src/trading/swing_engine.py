"""
SwingEngine: Daily swing trading engine for CNC delivery trades.
================================================================
Runs once daily (at market close) to:
1. Fetch latest daily candles for each stock
2. Check exit conditions on open positions
3. Scan for new entry signals
4. Execute via PaperTrader (or UpstoxClient for live)
5. Send Telegram notifications

Positions are persisted to a JSON file (data/swing_positions.json)
so they survive restarts across multiple trading days.
"""

from __future__ import annotations

import fcntl
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.backtest.swing_backtester import SwingConfig, SWING_TOKENS
from src.broker.upstox_client import UpstoxClient
from src.data.db_logger import ensure_schema, log_order
from src.indicators.technical import compute_atr
from src.notifications.telegram_bot import TelegramNotifier
from src.strategy.swing_signal_generator import SwingSignalGenerator, SwingSignalType
from src.trading.paper_trader import PaperTrader

logger = logging.getLogger(__name__)

try:
    from src.utils.ist_utils import IST, now_ist, today_ist_date_str
except ImportError:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    def now_ist():
        return datetime.now(IST)
    def today_ist_date_str():
        return now_ist().strftime("%Y-%m-%d")


POSITIONS_FILE = "data/swing_positions.json"


# Phase 3C: distinct exit code so systemd can refuse to restart-loop
# on auth failure. Mapped in deploy/swing-engine.service via
# RestartPreventExitStatus=75. (75 = EX_TEMPFAIL in BSD sysexits.)
AUTH_HALT_EXIT_CODE = 75


class AuthHaltError(RuntimeError):
    """Raised when Upstox returns 401. Engine MUST stop placing orders
    and exit with ``AUTH_HALT_EXIT_CODE``. Catching code must not retry."""
SWING_DB = "data/swing_trades.sqlite3"
WEEKLY_PNL_FILE = "data/swing_weekly_pnl.json"
CUMULATIVE_PNL_FILE = "data/swing_cumulative_pnl.json"


# ---------------------------------------------------------------------------
# Position persistence
# ---------------------------------------------------------------------------

@dataclass
class SwingPosition:
    """An open swing position (persisted to JSON)."""
    symbol: str
    instrument_token: str
    entry_price: float
    qty: int
    stop_loss: float
    target: float
    entry_date: str          # YYYY-MM-DD
    entry_atr: float
    order_id: str = ""
    days_held: int = 0
    best_price: float = 0.0
    entry_reasons: str = ""

    def __post_init__(self):
        if self.best_price == 0.0:
            self.best_price = self.entry_price

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SwingPosition:
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})


def load_positions(path: str = POSITIONS_FILE) -> Dict[str, SwingPosition]:
    """Load open positions from JSON file. Raises on corruption."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return {sym: SwingPosition.from_dict(pos) for sym, pos in data.items()}
    except (json.JSONDecodeError, KeyError) as e:
        # Corrupted file — do NOT silently return empty (could orphan live positions)
        logger.critical(f"POSITIONS FILE CORRUPTED: {p}: {e}")
        # Try backup
        bak = p.with_suffix(".json.bak")
        if bak.exists():
            logger.warning(f"Attempting to restore from backup {bak}")
            try:
                with open(bak) as f:
                    data = json.load(f)
                return {sym: SwingPosition.from_dict(pos) for sym, pos in data.items()}
            except Exception:
                pass
        raise RuntimeError(
            f"Position file corrupted at {p}, manual intervention required: {e}"
        )


def save_positions(positions: Dict[str, SwingPosition],
                   path: str = POSITIONS_FILE) -> None:
    """Save positions atomically (write tmp + rename) with backup."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing file
    if p.exists():
        shutil.copy2(p, p.with_suffix(".json.bak"))

    # Atomic write: write to temp, then rename
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump({sym: pos.to_dict() for sym, pos in positions.items()},
                  f, indent=2)
        f.flush()
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    tmp.rename(p)  # atomic on POSIX
    logger.info(f"Saved {len(positions)} positions to {p}")


# ---------------------------------------------------------------------------
# Weekly P&L tracking
# ---------------------------------------------------------------------------

def load_weekly_pnl(path: str = WEEKLY_PNL_FILE) -> Dict[str, Any]:
    """Load weekly P&L tracker. Resets on Monday."""
    p = Path(path)
    today = datetime.now().date()
    # Monday of this week
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    if p.exists():
        try:
            with open(p) as f:
                data = json.load(f)
            if data.get("week_start") == week_start:
                return data
        except (json.JSONDecodeError, KeyError):
            pass

    # New week or corrupted — reset
    return {"week_start": week_start, "realized_pnl": 0.0, "trades": []}


def save_weekly_pnl(data: Dict[str, Any], path: str = WEEKLY_PNL_FILE) -> None:
    """Save weekly P&L tracker."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Cumulative P&L tracking (for compounding)
# ---------------------------------------------------------------------------

def load_cumulative_pnl(path: str = CUMULATIVE_PNL_FILE) -> Dict[str, Any]:
    """Load lifetime cumulative P&L for compounding."""
    p = Path(path)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Cumulative P&L file corrupted, resetting: {p}")
    return {"base_budget": 30000.0, "cumulative_pnl": 0.0, "trade_count": 0,
            "last_updated": ""}


def save_cumulative_pnl(data: Dict[str, Any], path: str = CUMULATIVE_PNL_FILE) -> None:
    """Save cumulative P&L for compounding."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Daily candle fetching
# ---------------------------------------------------------------------------

def fetch_daily_candles(upstox: UpstoxClient, instrument_token: str,
                        days: int = 200) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV candles from Upstox historical API.

    Returns DataFrame with columns: open, high, low, close, volume
    indexed by date string (YYYY-MM-DD), sorted ascending.
    """
    today = now_ist().date()
    from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    try:
        resp = upstox.get_historical_candle(
            instrument_token, "day", from_date, to_date
        )
        candles = resp.get("data", {}).get("candles", [])
        if not candles:
            logger.warning(f"No daily candles for {instrument_token}")
            return None

        rows = []
        for c in candles:
            ts_str = c[0].split("+")[0].split("T")[0]
            rows.append({
                "date": ts_str,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]) if len(c) > 5 else 0,
            })

        df = pd.DataFrame(rows).set_index("date").sort_index()
        return df

    except Exception as e:
        logger.error(f"Failed to fetch daily candles for {instrument_token}: {e}")
        return None


# ---------------------------------------------------------------------------
# Charge estimation (CNC delivery)
# ---------------------------------------------------------------------------

def estimate_cnc_charges(qty: int, buy_price: float, sell_price: float) -> float:
    """Estimate round-trip CNC delivery charges."""
    bv = qty * buy_price
    sv = qty * sell_price
    turnover = bv + sv

    buy_brok = min(20.0, bv * 0.001)
    sell_brok = min(20.0, sv * 0.001)
    brokerage = buy_brok + sell_brok

    stt = bv * 0.001 + sv * 0.001       # 0.1% both sides CNC
    txn = turnover * 0.0000297
    ipft = turnover * 0.000001
    gst = (brokerage + txn + ipft) * 0.18
    sebi = turnover * 0.000001
    stamp = bv * 0.00015                  # 0.015% buy side CNC

    return brokerage + stt + txn + ipft + gst + sebi + stamp


# ---------------------------------------------------------------------------
# Swing Engine
# ---------------------------------------------------------------------------

class SwingEngine:
    """
    Daily swing trading engine.

    Designed to run once per day after market close (15:30 IST).
    Uses daily candles for signal generation and position management.
    """

    def __init__(self, config: SwingConfig, mode: str = "paper",
                 positions_file: str = POSITIONS_FILE):
        self.cfg = config
        self.mode = mode
        self.positions_file = positions_file
        self.tokens = dict(SWING_TOKENS)

        # Signal generator
        self.signal_gen = SwingSignalGenerator(config.strategy_dict())

        # Broker client (always needed for data)
        self.upstox = UpstoxClient()

        # Order executor
        if mode == "paper":
            self.executor = PaperTrader(slippage_pct=config.slippage_pct,
                                        db_path=SWING_DB)
        else:
            self.executor = self.upstox

        # Telegram
        self.notifier = TelegramNotifier()

        # DB
        ensure_schema(SWING_DB)

        # Initialize cumulative P&L base_budget from config
        cum = load_cumulative_pnl()
        if cum.get("base_budget", 0) != config.budget:
            cum["base_budget"] = config.budget
            save_cumulative_pnl(cum)

        # Parse earnings blackout dates
        self._earnings_dates: Dict[str, datetime] = {}
        for sym, date_str in config.earnings_blackout.items():
            try:
                self._earnings_dates[sym] = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Invalid earnings date for {sym}: {date_str}")

    @property
    def effective_budget(self) -> float:
        """Base budget + all realized profits (compounding)."""
        cum = load_cumulative_pnl()
        return self.cfg.budget + cum.get("cumulative_pnl", 0.0)

    # ------------------------------------------------------------------
    # Main daily scan
    # ------------------------------------------------------------------

    def run_daily_scan(self) -> Dict[str, Any]:
        """
        Execute the daily swing scan.

        Returns summary dict with actions taken.
        """
        today = today_ist_date_str()
        logger.info(f"=== Swing Engine Daily Scan: {today} ===")

        summary = {
            "date": today,
            "mode": self.mode,
            "exits": [],
            "entries": [],
            "open_positions": [],
            "errors": [],
        }

        # Load persisted positions
        positions = load_positions(self.positions_file)
        logger.info(f"Open positions: {list(positions.keys()) or 'none'}")

        # Fetch daily candles for all stocks
        daily_data: Dict[str, pd.DataFrame] = {}
        for sym, token in self.tokens.items():
            df = fetch_daily_candles(self.upstox, token)
            if df is not None and len(df) > 0:
                daily_data[sym] = df
                logger.info(f"  {sym}: {len(df)} daily bars, "
                            f"last close={df.iloc[-1]['close']:.2f}")
            else:
                summary["errors"].append(f"No data for {sym}")

        if not daily_data:
            msg = "No daily data available for any symbol"
            logger.error(msg)
            summary["errors"].append(msg)
            self._notify_sync(f"Swing scan failed: {msg}")
            return summary

        # --- Phase 1: Check exits on open positions ---
        for sym in list(positions.keys()):
            pos = positions[sym]

            if sym not in daily_data:
                logger.warning(f"No data for open position {sym}, skipping exit check")
                continue

            # Only increment days_held when we have trading data
            pos.days_held += 1

            bar = daily_data[sym].iloc[-1]
            day_open = float(bar["open"])
            day_high = float(bar["high"])
            day_low = float(bar["low"])
            day_close = float(bar["close"])

            pos.best_price = max(pos.best_price, day_high)

            exit_reason = None
            exit_price = None

            # Stop loss — handle gap-through (fill at open if gapped past SL)
            if day_low <= pos.stop_loss:
                exit_reason = "stop_loss"
                exit_price = min(pos.stop_loss, day_open)

            # Target — handle gap-through (fill at open if gapped past target)
            elif day_high >= pos.target:
                exit_reason = "target"
                exit_price = max(pos.target, day_open)

            # Max hold
            elif pos.days_held >= self.cfg.max_hold_days:
                exit_reason = "max_hold_days"
                exit_price = day_close

            # Stale trade
            elif (pos.days_held >= self.cfg.stale_trade_days
                  and day_close < pos.entry_price + 1.5 * pos.entry_atr):
                exit_reason = "stale_trade"
                exit_price = day_close

            if exit_reason:
                exit_info = self._execute_exit(pos, exit_price, exit_reason, today)
                # Only delete position if exit was successful
                if exit_info and exit_info.get("order_id") not in ("ERROR", "FAILED"):
                    summary["exits"].append(exit_info)
                    del positions[sym]
                else:
                    logger.error(f"Exit failed for {sym}, keeping position open")
                    summary["errors"].append(f"Exit failed for {sym}: {exit_reason}")

        # --- Phase 2: Pre-entry gates ---
        entries_blocked = False
        block_reason = ""
        now = datetime.now()
        current_weekday = now.weekday()

        # Gate: VIX safety check
        vix_val = self._fetch_vix()
        summary["vix"] = vix_val
        if vix_val is not None and vix_val > self.cfg.max_vix:
            entries_blocked = True
            block_reason = f"VIX {vix_val:.2f} > {self.cfg.max_vix}"
            logger.warning(f"  ENTRIES BLOCKED: {block_reason}")
            self._notify_sync(f"ENTRIES PAUSED: {block_reason}")

        # Phase 4 / addendum §B regime classifier — wired identically to the
        # walk-forward backtester. classify_regime() uses VIX(T-1) and Nifty
        # SMA(T-1) only (no same-bar leak). When the backtester runs with
        # regime ON the live engine must mirror it, or test results are
        # meaningless.
        from src.backtest.regime import classify_regime, RegimeConfig
        from src.utils.ist_utils import today_ist_date_str
        regime_cfg = RegimeConfig(enabled=True)
        today_str = today_ist_date_str()
        vix_series = self._fetch_vix_history()
        nifty_series = self._fetch_nifty_history()
        regime = classify_regime(today_str, vix_series, nifty_series, regime_cfg)
        summary["regime"] = {
            "vix": regime.vix.value, "trend": regime.trend.value,
            "size_multiplier": regime.size_multiplier,
            "threshold_multiplier": regime.threshold_multiplier,
            "blocked_groups": list(regime.blocked_groups),
            "block_all_entries": regime.block_all_entries,
        }
        if regime.block_all_entries and not entries_blocked:
            entries_blocked = True
            logger.warning(
                f"  ENTRIES BLOCKED: regime CRISIS (VIX T-1 close "
                f"{regime.vix_value if regime.vix_value is not None else '?'} "
                f"≥ crisis threshold)"
            )
            self._notify_sync(
                "Entries PAUSED today — regime CRISIS. Existing positions "
                "keep their stops (no panic-exit)."
            )
        elif regime.size_multiplier < 1.0:
            logger.warning(
                f"  Regime ELEVATED — sizing × {regime.size_multiplier}, "
                f"blocking groups: {list(regime.blocked_groups)}"
            )

        # Gate: Weekly loss limit (scales with effective budget)
        weekly_pnl = load_weekly_pnl()
        weekly_loss = weekly_pnl.get("realized_pnl", 0.0)
        max_weekly_loss = self.effective_budget * (self.cfg.max_weekly_loss_pct / 100.0)
        summary["weekly_pnl"] = weekly_loss
        if weekly_loss < 0 and abs(weekly_loss) >= max_weekly_loss:
            entries_blocked = True
            block_reason = (f"Weekly loss Rs.{weekly_loss:.0f} exceeds "
                           f"limit Rs.{max_weekly_loss:.0f}")
            logger.warning(f"  ENTRIES BLOCKED: {block_reason}")
            self._notify_sync(
                f"Weekly loss limit hit (Rs.{weekly_loss:.0f}), "
                f"entries paused until Monday"
            )

        # --- Phase 2: Scan for new entries ---
        if not entries_blocked and len(positions) < self.cfg.max_positions:
            for sym, df in daily_data.items():
                if sym in positions:
                    continue
                if len(positions) >= self.cfg.max_positions:
                    break

                # Gate: Swing-restricted stocks
                if sym in self.cfg.swing_restricted:
                    logger.info(f"  {sym}: RESTRICTED (skipping entry)")
                    continue

                # Phase 4 / addendum §B: ELEVATED VIX blocks specific
                # universe groups (e.g. high_beta_cyclicals). Symbol's
                # group is read from config/universe.yaml via the
                # universe loader. Symbols outside the universe (legacy
                # stocks.json) are treated as ungrouped and not blocked.
                sym_group = self._symbol_group(sym)
                if sym_group and sym_group in regime.blocked_groups:
                    logger.info(
                        f"  {sym}: blocked by regime "
                        f"({regime.vix.value} → group {sym_group})"
                    )
                    continue

                # Gate: Earnings blackout
                if sym in self._earnings_dates:
                    earnings_dt = self._earnings_dates[sym]
                    days_to_earnings = (earnings_dt.date() - now.date()).days
                    if -1 <= days_to_earnings <= 3:
                        logger.info(
                            f"  {sym}: earnings blackout "
                            f"({earnings_dt.strftime('%Y-%m-%d')}, "
                            f"{days_to_earnings}d away)"
                        )
                        continue

                # Check signal (with day-of-week filter)
                signal = self.signal_gen.generate_signal(
                    sym, df, current_weekday=current_weekday
                )
                if signal.type != SwingSignalType.BUY:
                    conds = sum(1 for r in signal.reasons if "[OK]" in r)
                    if conds >= 4:
                        logger.info(f"  {sym}: near-miss {conds}/6 conditions")
                    elif any("[GATE]" in r or "[SKIP]" in r for r in signal.reasons):
                        gate_reasons = [r for r in signal.reasons
                                       if "[GATE]" in r or "[SKIP]" in r]
                        logger.info(f"  {sym}: {'; '.join(gate_reasons)}")
                    continue

                atr = signal.atr
                if atr is None or atr <= 0:
                    continue

                entry_price = signal.price
                sl = round(entry_price - self.cfg.sl_atr_mult * atr, 2)
                target = round(entry_price + self.cfg.target_atr_mult * atr, 2)

                # Risk-based sizing (uses effective budget for compounding)
                risk_per_share = self.cfg.sl_atr_mult * atr
                budget = self.effective_budget
                max_risk = budget * (self.cfg.risk_per_trade_pct / 100.0)
                qty = int(max_risk / risk_per_share)

                invested = sum(p.entry_price * p.qty for p in positions.values())
                available = budget - invested
                max_qty_by_budget = int(available / entry_price) if entry_price > 0 else 0
                qty = min(qty, max_qty_by_budget)

                # Cap by max_position_pct of effective budget — never deploy
                # more than this fraction in one symbol.
                max_pos_pct = getattr(self.cfg, "max_position_pct", 20.0) or 20.0
                if max_pos_pct > 0 and entry_price > 0:
                    cap_value = budget * (max_pos_pct / 100.0)
                    max_qty_by_position_pct = int(cap_value / entry_price)
                    qty = min(qty, max_qty_by_position_pct)

                # Phase 4 / addendum §B: ELEVATED VIX shrinks position size.
                if regime.size_multiplier < 1.0 and qty > 0:
                    qty = max(0, int(qty * regime.size_multiplier))

                if qty <= 0:
                    logger.info(f"  {sym}: signal BUY but qty=0 (budget exhausted)")
                    continue

                # Cost-aware position-quality gate (Phase 2 spec): refuse
                # entries whose target profit can't clear round-trip costs
                # min_profit_cost_multiple-x (default 3x). Phase 4: in
                # downtrend the regime classifier inflates the multiple by
                # ``downtrend_signal_multiplier`` so weak setups get
                # filtered out even harder.
                from src.backtest.cost_model import DELIVERY_CNC, target_clears_costs
                min_mult = (
                    getattr(self.cfg, "min_profit_cost_multiple", 3.0)
                    * regime.threshold_multiplier
                )
                if not target_clears_costs(
                    qty, entry_price, target, DELIVERY_CNC, multiple=min_mult,
                ):
                    cost = DELIVERY_CNC.total(qty, entry_price, target)
                    profit_potential = (target - entry_price) * qty
                    logger.info(
                        f"  {sym}: signal BUY but target profit Rs.{profit_potential:.0f} "
                        f"only covers costs Rs.{cost:.0f} {profit_potential/cost:.2f}x "
                        f"(need {min_mult:.1f}x)"
                    )
                    continue

                entry_info = self._execute_entry(
                    sym, entry_price, qty, sl, target, atr, today
                )
                if entry_info:
                    # Recalculate SL/target from actual fill price (not signal price)
                    fill_price = entry_info["fill_price"]
                    actual_sl = round(fill_price - self.cfg.sl_atr_mult * atr, 2)
                    actual_target = round(fill_price + self.cfg.target_atr_mult * atr, 2)
                    positions[sym] = SwingPosition(
                        symbol=sym,
                        instrument_token=self.tokens[sym],
                        entry_price=fill_price,
                        qty=qty,
                        stop_loss=actual_sl,
                        target=actual_target,
                        entry_date=today,
                        entry_atr=atr,
                        order_id=entry_info["order_id"],
                        entry_reasons="; ".join(signal.reasons),
                    )
                    summary["entries"].append(entry_info)

        # Save updated positions
        save_positions(positions, self.positions_file)

        # Build summary
        for sym, pos in positions.items():
            current_close = float(daily_data[sym].iloc[-1]["close"]) if sym in daily_data else pos.entry_price
            unrealized = (current_close - pos.entry_price) * pos.qty
            summary["open_positions"].append({
                "symbol": sym,
                "entry": pos.entry_price,
                "current": current_close,
                "qty": pos.qty,
                "unrealized": round(unrealized, 2),
                "days_held": pos.days_held,
                "sl": pos.stop_loss,
                "target": pos.target,
            })

        # Send Telegram summary
        self._send_daily_summary(summary)

        return summary

    # ------------------------------------------------------------------
    # VIX fetch
    # ------------------------------------------------------------------

    def _fetch_vix(self) -> Optional[float]:
        """Return the most recent India VIX daily close STRICTLY before today.

        Phase 1 audit C4 + Phase 3D fix: the live engine previously called
        get_ltp("NSE_INDEX|India VIX"), which can leak current-day intraday
        VIX into the decision. The backtester now uses T-1 daily close;
        the live engine must match or the two diverge by exactly the
        regime-gate behavior we care about.

        Primary path: pull last 10 calendar days of daily candles and use
        the latest entry whose date is strictly before today (IST). Falls
        back to the LTP read with a logged WARNING only if the historical
        endpoint is unreachable — in which case the engine continues but
        operator should investigate.
        """
        try:
            today_str = today_ist_date_str()
            today_dt = datetime.strptime(today_str, "%Y-%m-%d").date()
            from_dt = today_dt - timedelta(days=10)
            resp = self.upstox.get_historical_candle(
                "NSE_INDEX|India VIX", "day",
                from_dt.strftime("%Y-%m-%d"), today_str,
            )
            candles = (resp or {}).get("data", {}).get("candles", []) or []
            # Each candle: [ts, open, high, low, close, volume, oi]
            for c in candles:  # Upstox returns newest-first
                ts = str(c[0])[:10]   # YYYY-MM-DD slice
                if ts < today_str:
                    vix = float(c[4])
                    logger.info(f"  VIX (T-1 close, {ts}): {vix:.2f}")
                    return vix
            logger.warning(
                "  VIX historical fetch returned no prior-day candle; "
                "falling back to LTP (may include same-bar leak)."
            )
        except Exception as e:
            logger.warning(
                f"  VIX historical fetch failed: {e}; falling back to LTP "
                "(may include same-bar leak)."
            )
        # Fallback path — logged loudly because it can leak.
        try:
            vix = self.upstox.get_ltp("NSE_INDEX|India VIX")
            logger.info(f"  VIX (LTP fallback): {vix:.2f}")
            return float(vix)
        except Exception as e:
            logger.warning(f"  VIX LTP fallback also failed: {e}")
            return None

    # ------------------------------------------------------------------
    # SEBI compliance helpers
    # ------------------------------------------------------------------

    def _fetch_history_close_series(
        self, instrument_key: str, days_back: int,
    ) -> Optional[pd.Series]:
        """Pull daily candles for ``instrument_key`` and return a Series
        of CLOSE values indexed by date string (YYYY-MM-DD). Used for the
        regime classifier (VIX series + Nifty SMA computation).

        Excludes today's bar — only T-1 and earlier — so no same-bar leak.
        """
        try:
            today_str = today_ist_date_str()
            today_dt = datetime.strptime(today_str, "%Y-%m-%d").date()
            from_dt = today_dt - timedelta(days=days_back)
            resp = self.upstox.get_historical_candle(
                instrument_key, "day",
                from_dt.strftime("%Y-%m-%d"), today_str,
            )
            candles = (resp or {}).get("data", {}).get("candles", []) or []
            data: List[Tuple[str, float]] = []
            for c in candles:
                ts = str(c[0])[:10]
                if ts < today_str:
                    data.append((ts, float(c[4])))
            if not data:
                return None
            data.sort(key=lambda r: r[0])
            ix = [r[0] for r in data]
            vals = [r[1] for r in data]
            return pd.Series(vals, index=ix)
        except Exception as e:
            logger.warning(
                f"  History fetch failed for {instrument_key}: {e}"
            )
            return None

    def _fetch_vix_history(self) -> Optional[pd.Series]:
        """India VIX daily closes for ~30 prior days (regime classifier)."""
        return self._fetch_history_close_series("NSE_INDEX|India VIX", 30)

    def _fetch_nifty_history(self) -> Optional[pd.Series]:
        """Nifty 50 daily closes for ~220 prior days (200d SMA needs 200+)."""
        return self._fetch_history_close_series("NSE_INDEX|Nifty 50", 220)

    def _symbol_group(self, symbol: str) -> Optional[str]:
        """Return the universe group name for ``symbol`` (e.g.
        ``high_beta_cyclicals``) or ``None`` if outside the universe."""
        cache = getattr(self, "_universe_s2g", None)
        if cache is None:
            try:
                from src.utils.universe import load_universe
                u = load_universe(strict=False)
                cache = u.symbol_to_group
            except Exception as e:
                logger.warning(f"universe load failed; group filter inactive: {e}")
                cache = {}
            self._universe_s2g = cache
        return cache.get(symbol)

    def _algo_name(self) -> Optional[str]:
        """Return ALGO_NAME from env (SEBI Generic Algo ID tier).

        In live mode the launcher's validate_live() already refuses startup
        when this is empty, so reaching ``_execute_entry/_exit`` implies
        a value (or a paper run). In paper mode we still pass it through —
        if unset, the executor logs a one-line warning so the operator
        sees the gap before going live.
        """
        import os as _os
        return _os.environ.get("ALGO_NAME", "").strip() or None

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _place_order_with_retry(self, max_retries: int = 2, **order_kwargs) -> Dict[str, Any]:
        """
        Place an order with retry on transient failures.
        Retries on network/timeout/5xx errors only. Does NOT retry on
        order rejections (400/422). On 401 the function raises
        :class:`AuthHaltError` immediately so the engine can halt order
        flow and exit with the distinct code mapped by systemd to
        "wait for token, do not restart-loop".
        """
        import requests as req

        backoff = [1.0, 3.0]
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                result = self.executor.place_order(**order_kwargs)
                return result
            # HTTPError must come BEFORE the OSError block — HTTPError
            # subclasses OSError via RequestException, and Python's
            # except dispatch picks the first matching block.
            except req.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response is not None:
                    if e.response.status_code == 401:
                        # Token dead — halt immediately, no retry. The
                        # launcher exits with AUTH_HALT_EXIT_CODE so
                        # systemd does NOT restart-loop on auth failure.
                        logger.error(
                            "Order rejected HTTP 401 — access token is "
                            "dead. Halting order placement and exiting."
                        )
                        self._notify_sync(
                            "AUTH HALT: Upstox returned 401 on order "
                            "placement. Token is dead.\n"
                            "Engine is stopping. systemd will NOT auto-"
                            "restart — re-auth via /login on Telegram "
                            "or wait for the daily token refresh."
                        )
                        raise AuthHaltError(
                            "Upstox returned 401; token dead"
                        ) from e
                    if e.response.status_code < 500:
                        logger.error(f"Order rejected (HTTP {e.response.status_code}): {e}")
                        raise
                last_error = e
                if attempt < max_retries:
                    wait = backoff[min(attempt, len(backoff) - 1)]
                    logger.warning(
                        f"Order attempt {attempt + 1}/{max_retries + 1} failed "
                        f"(HTTP): {e}. Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Order FAILED after {max_retries + 1} attempts: {e}")
            except (req.exceptions.ConnectionError,
                    req.exceptions.Timeout,
                    req.exceptions.ReadTimeout,
                    OSError) as e:
                last_error = e
                if attempt < max_retries:
                    wait = backoff[min(attempt, len(backoff) - 1)]
                    logger.warning(
                        f"Order attempt {attempt + 1}/{max_retries + 1} failed "
                        f"(network): {e}. Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Order FAILED after {max_retries + 1} attempts: {e}")

        return {"status": "error", "data": {"order_id": "FAILED", "price": 0},
                "error": str(last_error)}

    def _verify_order_fill(self, order_id: str, max_attempts: int = 3,
                           poll_interval: float = 2.0) -> Dict[str, Any]:
        """
        Poll Upstox order status to verify fill. Live mode only.
        Returns dict with keys: filled (bool), status (str), fill_price (float).
        In paper mode, always returns filled=True.
        """
        if self.mode == "paper":
            return {"filled": True, "status": "paper", "fill_price": 0}

        if order_id in ("FAILED", "ERROR", "N/A"):
            return {"filled": False, "status": order_id, "fill_price": 0}

        import time as _time
        for attempt in range(max_attempts):
            try:
                details = self.upstox.get_order_details(order_id)
                data = details.get("data", {})
                status = data.get("status", "").lower()

                if status in ("complete", "filled", "traded"):
                    avg_price = float(data.get("average_price", 0) or
                                     data.get("price", 0) or 0)
                    logger.info(f"Order {order_id} verified: {status}, "
                               f"avg_price={avg_price}")
                    return {"filled": True, "status": status,
                            "fill_price": avg_price}

                if status in ("rejected", "cancelled"):
                    reason = data.get("status_message", "unknown")
                    logger.error(f"Order {order_id} {status}: {reason}")
                    return {"filled": False, "status": status,
                            "fill_price": 0}

                # Still pending — wait and retry
                if attempt < max_attempts - 1:
                    logger.info(f"Order {order_id} status={status}, "
                               f"polling ({attempt + 1}/{max_attempts})...")
                    _time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Order status check failed for {order_id}: {e}")
                if attempt < max_attempts - 1:
                    _time.sleep(poll_interval)

        logger.warning(f"Order {order_id} status unconfirmed after {max_attempts} polls")
        return {"filled": False, "status": "unconfirmed", "fill_price": 0}

    def _execute_entry(self, symbol: str, price: float, qty: int,
                       sl: float, target: float, atr: float,
                       date: str) -> Optional[Dict[str, Any]]:
        """Execute a BUY order."""
        token = self.tokens.get(symbol, symbol)

        # SEBI static-IP gate (Phase 3B): block NEW orders while the
        # watcher reports a mismatch. Exits are never blocked.
        ip_watcher = getattr(self, "ip_watcher", None)
        if ip_watcher is not None and ip_watcher.mismatch.is_set():
            logger.error(
                f"  ENTRY BLOCKED {symbol}: static-IP mismatch — "
                "engine will not open new positions until IP is restored"
            )
            self._notify_sync(
                f"ENTRY BLOCKED {symbol}\n"
                "Static-IP mismatch detected mid-session.\n"
                "No new orders. Existing positions still managed."
            )
            return None

        try:
            result = self._place_order_with_retry(
                instrument_token=token,
                side="BUY",
                qty=qty,
                product="CNC",
                order_type="MARKET",
                price=price,
                tag="swing-entry",
                algo_name=self._algo_name(),
            )

            if result.get("status") != "success":
                logger.error(f"Entry order failed for {symbol}: {result}")
                self._notify_sync(f"ENTRY FAILED {symbol}: {result.get('error', 'unknown')}")
                return None

            fill_price = result["data"]["price"]
            order_id = result["data"]["order_id"]

            # In live mode, verify the entry order actually filled
            if self.mode == "live":
                verification = self._verify_order_fill(order_id)
                if not verification["filled"]:
                    logger.error(
                        f"ENTRY ORDER NOT CONFIRMED for {symbol} "
                        f"(order_id={order_id}, status={verification['status']})"
                    )
                    self._notify_sync(
                        f"ENTRY ORDER NOT CONFIRMED {symbol}\n"
                        f"Order: {order_id}\n"
                        f"Status: {verification['status']}\n"
                        f"ACTION REQUIRED: Check Upstox manually!"
                    )
                    return None
                elif verification["fill_price"] > 0:
                    fill_price = verification["fill_price"]

            logger.info(
                f"  ENTRY {symbol}: BUY {qty} @ {fill_price:.2f} "
                f"SL={sl:.2f} TGT={target:.2f} [{order_id}]"
            )

            # Telegram alert
            self._notify_sync(
                f"SWING BUY {symbol}\n"
                f"Qty: {qty} @ Rs.{fill_price:.2f}\n"
                f"SL: Rs.{sl:.2f} | TGT: Rs.{target:.2f}\n"
                f"ATR: Rs.{atr:.2f} | Risk: Rs.{qty * (fill_price - sl):.0f}\n"
                f"Date: {date}"
            )

            return {
                "symbol": symbol,
                "side": "BUY",
                "qty": qty,
                "fill_price": fill_price,
                "order_id": order_id,
                "sl": sl,
                "target": target,
                "atr": atr,
                "date": date,
            }

        except Exception as e:
            logger.error(f"Entry execution error for {symbol}: {e}")
            return None

    def _execute_exit(self, pos: SwingPosition, exit_price: float,
                      reason: str, date: str) -> Dict[str, Any]:
        """Execute a SELL order to close position."""
        try:
            result = self._place_order_with_retry(
                instrument_token=pos.instrument_token,
                side="SELL",
                qty=pos.qty,
                product="CNC",
                order_type="MARKET",
                price=exit_price,
                tag=f"swing-exit-{reason}",
                algo_name=self._algo_name(),
            )

            fill_price = result["data"]["price"] if result.get("status") == "success" else exit_price
            order_id = result["data"].get("order_id", "N/A") if result.get("status") == "success" else "FAILED"

        except Exception as e:
            logger.error(f"Exit execution error for {pos.symbol}: {e}")
            fill_price = exit_price
            order_id = "ERROR"

        # In live mode, verify the exit order actually filled
        if self.mode == "live" and order_id not in ("ERROR", "FAILED"):
            verification = self._verify_order_fill(order_id)
            if not verification["filled"]:
                logger.error(
                    f"EXIT ORDER NOT CONFIRMED for {pos.symbol} "
                    f"(order_id={order_id}, status={verification['status']}). "
                    f"Position will be RETAINED."
                )
                self._notify_sync(
                    f"EXIT ORDER NOT CONFIRMED {pos.symbol}\n"
                    f"Order: {order_id}\n"
                    f"Status: {verification['status']}\n"
                    f"ACTION REQUIRED: Check Upstox manually!"
                )
                order_id = "FAILED"  # Force position retention
            elif verification["fill_price"] > 0:
                fill_price = verification["fill_price"]  # Use actual fill price

        charges = estimate_cnc_charges(pos.qty, pos.entry_price, fill_price)
        gross_pnl = (fill_price - pos.entry_price) * pos.qty
        net_pnl = gross_pnl - charges

        logger.info(
            f"  EXIT {pos.symbol}: SELL {pos.qty} @ {fill_price:.2f} "
            f"reason={reason} gross={gross_pnl:+.2f} charges={charges:.2f} "
            f"net={net_pnl:+.2f} held={pos.days_held}d [{order_id}]"
        )

        emoji = "+" if net_pnl >= 0 else ""
        self._notify_sync(
            f"SWING SELL {pos.symbol} ({reason})\n"
            f"Qty: {pos.qty} @ Rs.{fill_price:.2f}\n"
            f"Entry: Rs.{pos.entry_price:.2f} on {pos.entry_date}\n"
            f"Gross: Rs.{gross_pnl:+.2f} | Charges: Rs.{charges:.2f}\n"
            f"Net P&L: Rs.{emoji}{net_pnl:.2f}\n"
            f"Held: {pos.days_held} days"
        )

        # Update weekly P&L tracker
        if order_id not in ("ERROR", "FAILED"):
            try:
                weekly = load_weekly_pnl()
                weekly["realized_pnl"] = weekly.get("realized_pnl", 0.0) + net_pnl
                weekly["trades"].append({
                    "symbol": pos.symbol, "net_pnl": round(net_pnl, 2),
                    "date": date, "reason": reason,
                })
                save_weekly_pnl(weekly)
            except Exception as e:
                logger.error(f"Weekly P&L tracking failed: {e}")

        # Update cumulative P&L for compounding
        if order_id not in ("ERROR", "FAILED"):
            try:
                cum = load_cumulative_pnl()
                cum["cumulative_pnl"] = cum.get("cumulative_pnl", 0.0) + net_pnl
                cum["trade_count"] = cum.get("trade_count", 0) + 1
                cum["last_updated"] = date
                save_cumulative_pnl(cum)
                logger.info(f"  Cumulative P&L: Rs.{cum['cumulative_pnl']:+.2f} "
                            f"(effective budget: Rs.{self.cfg.budget + cum['cumulative_pnl']:,.0f})")
            except Exception as e:
                logger.error(f"Cumulative P&L tracking failed: {e}")

        return {
            "symbol": pos.symbol,
            "side": "SELL",
            "qty": pos.qty,
            "entry_price": pos.entry_price,
            "exit_price": fill_price,
            "gross_pnl": round(gross_pnl, 2),
            "charges": round(charges, 2),
            "net_pnl": round(net_pnl, 2),
            "reason": reason,
            "days_held": pos.days_held,
            "entry_date": pos.entry_date,
            "exit_date": date,
            "order_id": order_id,
        }

    # ------------------------------------------------------------------
    # Telegram helpers
    # ------------------------------------------------------------------

    def _notify_sync(self, text: str) -> None:
        """Send Telegram notification (sync wrapper)."""
        if not self.notifier.enabled:
            return
        try:
            self.notifier.send_sync(text)
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def _send_daily_summary(self, summary: Dict[str, Any]) -> None:
        """Send end-of-day summary via Telegram."""
        lines = [f"SWING SCAN — {summary['date']} ({self.mode})"]
        lines.append("")

        if summary["exits"]:
            lines.append(f"Exits: {len(summary['exits'])}")
            total_pnl = sum(e.get("net_pnl", 0) for e in summary["exits"])
            for e in summary["exits"]:
                lines.append(
                    f"  {e['symbol']}: Rs.{e.get('net_pnl', 0):+.2f} ({e.get('reason', '')})"
                )
            lines.append(f"  Total: Rs.{total_pnl:+.2f}")
            lines.append("")

        if summary["entries"]:
            lines.append(f"New entries: {len(summary['entries'])}")
            for e in summary["entries"]:
                lines.append(
                    f"  {e['symbol']}: {e['qty']} @ Rs.{e['fill_price']:.2f}"
                )
            lines.append("")

        if summary["open_positions"]:
            lines.append(f"Open positions: {len(summary['open_positions'])}")
            total_unrealized = 0
            for p in summary["open_positions"]:
                total_unrealized += p["unrealized"]
                lines.append(
                    f"  {p['symbol']}: Rs.{p['unrealized']:+.2f} "
                    f"({p['days_held']}d, SL={p['sl']:.0f} TGT={p['target']:.0f})"
                )
            lines.append(f"  Unrealized: Rs.{total_unrealized:+.2f}")
        else:
            lines.append("No open positions")

        if summary["errors"]:
            lines.append(f"\nErrors: {summary['errors']}")

        self._notify_sync("\n".join(lines))

    # ------------------------------------------------------------------
    # Status / utility
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        positions = load_positions(self.positions_file)
        cum = load_cumulative_pnl()
        return {
            "mode": self.mode,
            "open_positions": len(positions),
            "positions": {sym: pos.to_dict() for sym, pos in positions.items()},
            "budget": self.cfg.budget,
            "effective_budget": self.effective_budget,
            "cumulative_pnl": cum.get("cumulative_pnl", 0.0),
            "trade_count": cum.get("trade_count", 0),
            "max_positions": self.cfg.max_positions,
            "stocks": list(self.tokens.keys()),
        }

    def reconcile_positions(self) -> Dict[str, Any]:
        """
        Reconcile local position JSON with Upstox broker holdings.
        Live mode only. Alerts on mismatches but does NOT auto-fix.
        """
        result = {
            "orphaned_in_broker": [],
            "ghost_in_json": [],
            "matched": [],
            "status": "ok",
        }

        if self.mode == "paper":
            logger.info("Reconciliation skipped (paper mode)")
            result["status"] = "skipped_paper"
            return result

        positions = load_positions(self.positions_file)

        try:
            holdings_resp = self.upstox.get_holdings()
            holdings_data = holdings_resp.get("data", [])
        except Exception as e:
            logger.error(f"Cannot fetch holdings for reconciliation: {e}")
            self._notify_sync(
                f"RECONCILIATION FAILED\n"
                f"Cannot fetch Upstox holdings: {e}\n"
                f"Manual check required!"
            )
            result["status"] = "error"
            return result

        our_symbols = set(positions.keys())
        watchlist = set(self.tokens.keys())
        broker_holdings = {}
        for h in holdings_data:
            sym = (h.get("tradingsymbol") or h.get("trading_symbol") or "").upper()
            qty = int(h.get("quantity", 0))
            if sym in watchlist and qty > 0:
                broker_holdings[sym] = {
                    "qty": qty,
                    "avg_price": float(h.get("average_price", 0)),
                    "last_price": float(h.get("last_price", h.get("close_price", 0))),
                }

        broker_symbols = set(broker_holdings.keys())

        orphaned = broker_symbols - our_symbols
        ghosts = our_symbols - broker_symbols
        matched = our_symbols & broker_symbols

        for sym in orphaned:
            h = broker_holdings[sym]
            result["orphaned_in_broker"].append({
                "symbol": sym, "qty": h["qty"], "avg_price": h["avg_price"],
            })
            logger.warning(
                f"ORPHANED IN BROKER: {sym} ({h['qty']} shares @ {h['avg_price']:.2f}) "
                f"— not in swing_positions.json"
            )

        for sym in ghosts:
            pos = positions[sym]
            result["ghost_in_json"].append({
                "symbol": sym, "qty": pos.qty, "entry_price": pos.entry_price,
            })
            logger.warning(
                f"GHOST IN JSON: {sym} ({pos.qty} shares @ {pos.entry_price:.2f}) "
                f"— not found in Upstox holdings"
            )

        for sym in matched:
            pos = positions[sym]
            h = broker_holdings[sym]
            qty_match = pos.qty == h["qty"]
            result["matched"].append({
                "symbol": sym, "qty_match": qty_match,
                "json_qty": pos.qty, "broker_qty": h["qty"],
            })
            if not qty_match:
                logger.warning(
                    f"QTY MISMATCH: {sym} — JSON has {pos.qty}, broker has {h['qty']}"
                )

        qty_mismatches = [m for m in result["matched"] if not m["qty_match"]]

        if orphaned or ghosts or qty_mismatches:
            lines = ["POSITION RECONCILIATION ALERT\n"]
            if orphaned:
                lines.append("IN BROKER BUT NOT TRACKED:")
                for o in result["orphaned_in_broker"]:
                    lines.append(f"  {o['symbol']}: {o['qty']} @ {o['avg_price']:.2f}")
            if ghosts:
                lines.append("TRACKED BUT NOT IN BROKER:")
                for g in result["ghost_in_json"]:
                    lines.append(f"  {g['symbol']}: {g['qty']} @ {g['entry_price']:.2f}")
            if qty_mismatches:
                lines.append("QTY MISMATCH:")
                for m in qty_mismatches:
                    lines.append(
                        f"  {m['symbol']}: JSON={m['json_qty']}, Broker={m['broker_qty']}"
                    )
            lines.append("\nACTION REQUIRED: Review and fix manually.")
            self._notify_sync("\n".join(lines))
            result["status"] = "mismatch"
        else:
            logger.info(f"Reconciliation OK: {len(matched)} positions match")

        return result

    def monitor_positions(self) -> Dict[str, Any]:
        """
        Live position monitor — check current LTP against SL/target.

        Returns dict with position statuses and any exits triggered.
        """
        positions = load_positions(self.positions_file)
        if not positions:
            return {"positions": [], "exits": [], "status": "no_positions"}

        today = today_ist_date_str()
        result = {"positions": [], "exits": [], "status": "ok"}

        for sym in list(positions.keys()):
            pos = positions[sym]
            try:
                ltp = self.upstox.get_ltp(pos.instrument_token)
            except Exception as e:
                logger.error(f"Cannot get LTP for {sym}: {e}")
                result["positions"].append({
                    "symbol": sym, "error": str(e),
                })
                continue

            unrealized = (ltp - pos.entry_price) * pos.qty
            pnl_pct = (ltp - pos.entry_price) / pos.entry_price * 100
            dist_to_sl = (ltp - pos.stop_loss) / ltp * 100
            dist_to_tgt = (pos.target - ltp) / ltp * 100

            pos_info = {
                "symbol": sym,
                "ltp": ltp,
                "entry": pos.entry_price,
                "qty": pos.qty,
                "unrealized": round(unrealized, 2),
                "pnl_pct": round(pnl_pct, 2),
                "sl": pos.stop_loss,
                "target": pos.target,
                "dist_to_sl": round(dist_to_sl, 2),
                "dist_to_tgt": round(dist_to_tgt, 2),
                "days_held": pos.days_held,
                "entry_date": pos.entry_date,
            }

            # Check SL hit
            if ltp <= pos.stop_loss:
                logger.warning(f"SL HIT for {sym}! LTP={ltp:.2f} <= SL={pos.stop_loss:.2f}")
                exit_info = self._execute_exit(pos, ltp, "stop_loss", today)
                if exit_info and exit_info.get("order_id") not in ("ERROR", "FAILED"):
                    result["exits"].append(exit_info)
                    del positions[sym]
                    pos_info["action"] = "SL_EXIT"
                else:
                    pos_info["action"] = "SL_HIT_EXIT_FAILED"

            # Check target hit
            elif ltp >= pos.target:
                logger.info(f"TARGET HIT for {sym}! LTP={ltp:.2f} >= TGT={pos.target:.2f}")
                exit_info = self._execute_exit(pos, ltp, "target", today)
                if exit_info and exit_info.get("order_id") not in ("ERROR", "FAILED"):
                    result["exits"].append(exit_info)
                    del positions[sym]
                    pos_info["action"] = "TARGET_EXIT"
                else:
                    pos_info["action"] = "TGT_HIT_EXIT_FAILED"
            else:
                pos_info["action"] = "HOLDING"

            result["positions"].append(pos_info)

        # Save if any exits happened
        if result["exits"]:
            save_positions(positions, self.positions_file)

        return result

    def force_close_all(self, reason: str = "manual_close") -> List[Dict]:
        """Force close all open positions at current market price."""
        positions = load_positions(self.positions_file)
        if not positions:
            logger.info("No open positions to close")
            return []

        today = today_ist_date_str()
        exits = []

        for sym, pos in list(positions.items()):
            try:
                ltp = self.upstox.get_ltp(pos.instrument_token)
            except Exception as e:
                logger.error(f"Cannot get LTP for {sym}, skipping close: {e}")
                self._notify_sync(f"ALERT: Failed to close {sym} — LTP unavailable")
                continue

            exit_info = self._execute_exit(pos, ltp, reason, today)
            if exit_info and exit_info.get("order_id") not in ("ERROR", "FAILED"):
                exits.append(exit_info)
                del positions[sym]
            else:
                logger.error(f"Force close failed for {sym}, position retained")

        save_positions(positions, self.positions_file)
        return exits
