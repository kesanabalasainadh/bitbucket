#!/usr/bin/env python3
"""
Walk-forward harness (Phase 4 / main spec + addendum §D).

Rolling windows: train/tune on 18 months, test on the next 6 months,
step 6 months. **NO** parameter is chosen using test data — this
harness does not tune; tuning is intentionally out of scope here so
the report's verdict is honest. Parameters are taken from
``config/swing_config.yaml`` exactly as the live engine would use them.

For every window:
  * Loads historical daily candles from ``src.data.candle_cache`` for
    every symbol in the selected universe groups (defaults to all).
  * Applies the historical liquidity floor PER WINDOW so symbols
    illiquid at the time are excluded then (not retroactively from
    today's liquidity — that would be survivorship-style bias).
  * Runs ``SwingBacktester`` on the test window with regime ON.
  * Runs the same window with regime OFF (comparison).
  * Captures per-group, per-VIX-tier, per-trend-tier metrics.

Baselines run over the FULL period:
  * Nifty 50 equal-weight buy-and-hold (net of CostModel).
  * 7% FD baseline ("do nothing").

Output:
  reports/walkforward_<YYYY-MM-DD-HHMM>.md
  reports/walkforward_<YYYY-MM-DD-HHMM>.json
  reports/walkforward_<YYYY-MM-DD-HHMM>.png  (equity curve)

The summary is intentionally written to be brutal — if the strategy
fails to beat both baselines net of costs, the summary section says so
plainly and lists the top three drivers from the trade log.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

import pandas as pd

from src.backtest.cost_model import DELIVERY_CNC
from src.backtest.regime import RegimeConfig
from src.backtest.swing_backtester import SwingBacktester, SwingConfig
from src.data.candle_cache import CandleCache
from src.utils.universe import filter_by_liquidity, load_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("walkforward")


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    @property
    def label(self) -> str:
        return f"{self.test_start}_to_{self.test_end}"


def make_windows(
    overall_start: str, overall_end: str,
    train_months: int = 18, test_months: int = 6, step_months: int = 6,
) -> List[Window]:
    """Build the rolling-window schedule. The first window starts when
    we have at least ``train_months`` of warmup; the last window ends
    no later than ``overall_end``."""
    fmt = "%Y-%m-%d"
    s = datetime.strptime(overall_start, fmt).date()
    e = datetime.strptime(overall_end, fmt).date()
    windows: List[Window] = []
    train_start = s
    while True:
        train_end = _add_months(train_start, train_months) - timedelta(days=1)
        test_start = train_end + timedelta(days=1)
        test_end = _add_months(test_start, test_months) - timedelta(days=1)
        if test_end > e:
            break
        windows.append(Window(
            train_start.isoformat(), train_end.isoformat(),
            test_start.isoformat(), test_end.isoformat(),
        ))
        train_start = _add_months(train_start, step_months)
    return windows


def _add_months(d, months):
    # Lightweight month math without dateutil.
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return d.replace(year=y, month=m + 1, day=1)


# ---------------------------------------------------------------------------
# Universe / data loading
# ---------------------------------------------------------------------------

def load_candles_for(
    cache: CandleCache, instrument_keys: Dict[str, str],
    start: str, end: str,
) -> Dict[str, pd.DataFrame]:
    """Pull each symbol's daily bars from the cache and index by date string."""
    out: Dict[str, pd.DataFrame] = {}
    for sym, key in instrument_keys.items():
        if not key:
            continue
        df = cache.range(key, start, end)
        if df.empty:
            continue
        out[sym] = df.sort_index()
    return out


def load_series(cache: CandleCache, key: str, start: str, end: str) -> pd.Series:
    df = cache.range(key, start, end)
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"].astype(float)


# ---------------------------------------------------------------------------
# Tick fabrication for the backtester
# ---------------------------------------------------------------------------

def daily_to_ticks(
    daily_data: Dict[str, pd.DataFrame],
) -> Dict[str, List[Dict]]:
    """The SwingBacktester runs on per-symbol tick lists which it then
    re-aggregates to daily bars internally. For the walk-forward we
    *start* with daily bars from the cache, so we synthesize one tick
    per day per symbol carrying the bar's OHLCV. Re-aggregation is a
    no-op on this shape (groupby first/max/min/last/sum on a single row)."""
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    out: Dict[str, List[Dict]] = {}
    for sym, df in daily_data.items():
        ticks: List[Dict] = []
        for ts_str, row in df.iterrows():
            ts = datetime.strptime(str(ts_str)[:10], "%Y-%m-%d").replace(
                hour=9, minute=15, tzinfo=IST,
            )
            ticks.append({
                "symbol": sym, "timestamp": ts,
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]),   "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })
        out[sym] = ticks
    return out


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def buy_and_hold_equal_weight(
    daily_data: Dict[str, pd.DataFrame],
    start_capital: float,
    start: str, end: str,
) -> Dict[str, Any]:
    """Equal-weight buy-and-hold across the universe symbols that have
    coverage between ``start`` and ``end``. Costs: one buy on day 0,
    one sell on the last day, via ``DELIVERY_CNC`` cost model.

    Uses the FIRST bar at-or-after ``start`` and the LAST bar at-or-before
    ``end`` so holidays/weekends don't drop the comparison.
    """
    eligible = []
    bounds: Dict[str, tuple] = {}
    for s, df in daily_data.items():
        in_range = df[(df.index >= start) & (df.index <= end)]
        if len(in_range) < 2:
            continue
        eligible.append(s)
        bounds[s] = (in_range.index[0], in_range.index[-1])
    if not eligible:
        # Try the closest available bars when exact dates are missing
        # (weekend / holiday alignment). Fall back to first/last index
        # within [start, end].
        return {
            "label": "BUY_AND_HOLD_NIFTY_EW",
            "trades": 0,
            "pnl_gross": 0.0, "pnl_charges": 0.0, "pnl_net": 0.0,
            "ret_pct": 0.0,
            "final_equity": start_capital,
            "note": ("Skipped — no symbol had both start and end bars present. "
                     "Likely a holiday/weekend alignment issue."),
        }
    per_symbol = start_capital / len(eligible)
    total_gross = 0.0
    total_cost = 0.0
    for s in eligible:
        df = daily_data[s]
        s_date, e_date = bounds[s]
        entry = float(df.loc[s_date, "open"])
        exit_  = float(df.loc[e_date, "close"])
        qty = int(per_symbol / entry) if entry > 0 else 0
        if qty <= 0:
            continue
        gross = (exit_ - entry) * qty
        cost = DELIVERY_CNC.total(qty, entry, exit_)
        total_gross += gross
        total_cost += cost
    net = total_gross - total_cost
    return {
        "label": "BUY_AND_HOLD_NIFTY_EW",
        "trades": len(eligible),
        "pnl_gross": round(total_gross, 2),
        "pnl_charges": round(total_cost, 2),
        "pnl_net": round(net, 2),
        "ret_pct": round(net / start_capital, 6) if start_capital > 0 else 0.0,
        "final_equity": round(start_capital + net, 2),
    }


def fd_baseline(start_capital: float, start: str, end: str,
                annual_rate: float = 0.07) -> Dict[str, Any]:
    """7% annual fixed deposit, daily compounding."""
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end,   "%Y-%m-%d").date()
    years = (d1 - d0).days / 365.25
    final = start_capital * ((1.0 + annual_rate) ** years)
    return {
        "label": f"FD_{int(annual_rate*100)}PCT",
        "annual_rate": annual_rate,
        "years": round(years, 3),
        "pnl_net": round(final - start_capital, 2),
        "ret_pct": round((final - start_capital) / start_capital, 6),
        "final_equity": round(final, 2),
    }


# ---------------------------------------------------------------------------
# Honesty report
# ---------------------------------------------------------------------------

def explain_underperformance(report) -> List[str]:
    """Return up to three short reasons why the strategy underperformed,
    derived from the trade log. Used only when the strategy fails to
    beat both baselines."""
    reasons: List[str] = []
    trades = report.trade_log
    if not trades:
        return ["No trades were taken in the test windows."]
    losses = [t for t in trades if t["pnl"] < 0]
    if losses:
        cost_drag = sum(t["charges"] for t in trades) / max(
            sum(t["gross_pnl"] for t in trades), 1e-9,
        )
        if cost_drag > 0.5:
            reasons.append(
                f"Cost drag: round-trip charges ate "
                f"{cost_drag * 100:.0f}% of gross P&L."
            )
    sl_hits = [t for t in trades if t.get("reason") == "stop_loss"]
    if len(sl_hits) >= max(3, int(0.4 * len(trades))):
        reasons.append(
            f"Whipsaws: {len(sl_hits)} of {len(trades)} trades "
            f"({len(sl_hits)/len(trades):.0%}) exited at the stop."
        )
    stale = [t for t in trades if t.get("reason") == "stale_trade"]
    if len(stale) >= int(0.25 * len(trades)):
        reasons.append(
            f"Stale trades: {len(stale)} positions "
            f"timed out without reaching target."
        )
    return reasons[:3] if reasons else [
        "No single dominant failure mode — strategy edge may just be too small "
        "relative to costs over this period."
    ]


# ---------------------------------------------------------------------------
# Equity curve plot (optional)
# ---------------------------------------------------------------------------

def plot_equity_curve(
    out_path: Path,
    strategy_daily: Dict[str, float],
    bh_curve: Optional[Dict[str, float]] = None,
) -> bool:
    """Plot strategy equity vs baseline. Returns False if matplotlib unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    fig, ax = plt.subplots(figsize=(10, 4.5))
    if strategy_daily:
        dates = sorted(strategy_daily.keys())
        vals = []
        cum = 0.0
        for d in dates:
            cum += strategy_daily[d]
            vals.append(cum)
        ax.plot(dates, vals, label="strategy", color="C0")
    if bh_curve:
        dates = sorted(bh_curve.keys())
        ax.plot(dates, [bh_curve[d] for d in dates],
                label="buy_and_hold_EW", color="C1", linestyle="--")
    ax.set_xlabel("date")
    ax.set_ylabel("cumulative net P&L (INR)")
    ax.set_title("Walk-forward equity curve")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_walkforward(
    overall_start: str,
    overall_end: str,
    config_path: str,
    universe_path: str,
    groups: Optional[List[str]],
    report_dir: Path,
    use_postgres: bool = True,
    holdout_from: Optional[str] = None,
) -> Path:
    """Run the walk-forward harness.

    ``holdout_from`` (YYYY-MM-DD): when set, any window whose test_start
    falls on or after this date is DROPPED from the run. Used during
    iterative redesign to keep a pristine final-exam dataset that the
    redesigned rules will get to see exactly once at the end.
    """
    cfg = SwingConfig.from_yaml(config_path)
    universe = load_universe(universe_path, strict=False).select(groups)
    sym_keys = universe.symbol_to_instrument_key
    s2g = universe.symbol_to_group
    logger.info("universe: %d symbols across %d groups",
                len(sym_keys), len(universe.groups))

    cache = CandleCache(use_postgres=use_postgres)
    try:
        all_daily = load_candles_for(
            cache, sym_keys, overall_start, overall_end,
        )
        vix = load_series(cache, "NSE_INDEX|India VIX",   overall_start, overall_end)
        nifty = load_series(cache, "NSE_INDEX|Nifty 50",  overall_start, overall_end)
    finally:
        cache.close()

    if not all_daily:
        raise SystemExit(
            "No candle data found. Run scripts/fetch_historical.py first."
        )

    windows = make_windows(overall_start, overall_end)
    if holdout_from:
        before = len(windows)
        windows = [w for w in windows if w.test_start < holdout_from]
        dropped = before - len(windows)
        if dropped > 0:
            logger.warning(
                "HOLDOUT — dropped %d window(s) whose test period "
                "starts on or after %s. These bars are reserved for the "
                "final exam; iterative runs MUST NOT touch them.",
                dropped, holdout_from,
            )
    logger.info("schedule: %d windows", len(windows))

    per_window: List[Dict[str, Any]] = []
    cumulative_daily_pnl: Dict[str, float] = {}

    for w in windows:
        # Symbols liquid enough at the end of the train window. Liquidity
        # is measured on the EOT of the training period — strictly before
        # the test window — so no test-window data informs the filter.
        liquid = filter_by_liquidity(
            sym_keys.keys(), all_daily, w.train_end,
            floor_inr=universe.liquidity_floor_inr,
        )
        # Restrict candles to symbols passing liquidity, then to test range.
        wdata = {
            s: all_daily[s].loc[w.train_start:w.test_end]
            for s in liquid if s in all_daily
        }
        if not wdata:
            logger.warning("[%s] no liquid symbols; skipping", w.label)
            continue
        ticks = daily_to_ticks(wdata)

        for mode, regime_enabled in (("regime_on", True), ("regime_off", False)):
            bt = SwingBacktester(
                cfg,
                vix_series=vix,
                nifty_series=nifty,
                regime_config=RegimeConfig(enabled=regime_enabled),
                symbol_to_group=s2g,
            )
            report = bt.run(ticks)
            # Restrict daily_pnl to the TEST window only so the train
            # period's noop bars don't pad the curve.
            test_daily_pnl = {
                d: v for d, v in report.daily_pnl.items()
                if w.test_start <= d <= w.test_end
            }
            net = sum(test_daily_pnl.values())
            # Phase 4 diagnosis capture (questions Q1 and Q4 of
            # scripts/diagnose_walkforward.py): per-window gross / costs /
            # avg-win / avg-loss + a per-trade ratio of profit-at-target
            # over round-trip-cost. Filtered to trades that EXITED in the
            # test window so train-window simulation noise doesn't pad
            # the numbers.
            test_trades = [
                t for t in report.trade_log
                if w.test_start <= t.get("exit_date", "") <= w.test_end
            ]
            gross = sum(t.get("gross_pnl", 0.0) for t in test_trades)
            charges = sum(t.get("charges", 0.0) for t in test_trades)
            wins = [t["pnl"] for t in test_trades if t["pnl"] > 0]
            losses = [t["pnl"] for t in test_trades if t["pnl"] <= 0]
            avg_win = (sum(wins) / len(wins)) if wins else 0.0
            avg_loss = (sum(losses) / len(losses)) if losses else 0.0
            hold_days = [t.get("days_held", 0) for t in test_trades]
            avg_hold = (sum(hold_days) / len(hold_days)) if hold_days else 0.0
            # Per-trade target/cost ratio — feeds the histogram in the
            # diagnosis. round_trip_cost is what we stored as "charges";
            # profit-at-target is (target - entry) * qty.
            target_cost_ratios: List[float] = []
            for t in test_trades:
                tgt = t.get("target")
                ent = t.get("entry_price")
                qty = t.get("qty", 0)
                ch = t.get("charges", 0.0)
                if tgt is None or ent is None or ch <= 0 or qty <= 0:
                    continue
                profit_at_target = (float(tgt) - float(ent)) * int(qty)
                target_cost_ratios.append(round(profit_at_target / ch, 3))

            per_window.append({
                "window": w.label, "mode": mode,
                "trades": report.total_trades,
                "net_pnl": round(net, 2),
                "gross_pnl": round(gross, 2),
                "total_charges": round(charges, 2),
                "avg_holding_days": round(avg_hold, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "target_cost_ratios": target_cost_ratios,
                "win_rate": report.win_rate,
                "max_dd": report.max_drawdown,
                "per_group": report.per_group,
                "per_vix_regime": report.per_vix_regime,
                "per_market_trend": report.per_market_trend,
                "skip_counters": report.skip_counters,
            })
            if mode == "regime_on":
                for d, v in test_daily_pnl.items():
                    cumulative_daily_pnl[d] = cumulative_daily_pnl.get(d, 0.0) + v

    # Baselines over the entire test period
    earliest_test_start = windows[0].test_start if windows else overall_start
    latest_test_end = windows[-1].test_end if windows else overall_end
    bh = buy_and_hold_equal_weight(
        all_daily, cfg.budget, earliest_test_start, latest_test_end,
    )
    fd = fd_baseline(cfg.budget, earliest_test_start, latest_test_end)

    strategy_net = sum(
        r["net_pnl"] for r in per_window if r["mode"] == "regime_on"
    )
    strategy_ret_pct = strategy_net / cfg.budget if cfg.budget > 0 else 0.0
    beat_bh = strategy_net > bh["pnl_net"]
    beat_fd = strategy_net > fd["pnl_net"]

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    md_path = report_dir / f"walkforward_{stamp}.md"
    json_path = report_dir / f"walkforward_{stamp}.json"
    png_path = report_dir / f"walkforward_{stamp}.png"

    plot_equity_curve(png_path, cumulative_daily_pnl)

    summary = {
        "overall_start": overall_start, "overall_end": overall_end,
        "holdout_from": holdout_from,
        "windows": [w.__dict__ for w in windows],
        "per_window": per_window,
        "baseline_buy_and_hold": bh,
        "baseline_fd_7pct": fd,
        "strategy_net_pnl": round(strategy_net, 2),
        "strategy_ret_pct": round(strategy_ret_pct, 6),
        "beats_buy_and_hold": beat_bh,
        "beats_fd": beat_fd,
    }
    json_path.write_text(json.dumps(summary, indent=2, default=str))
    md_path.write_text(_render_md(summary, cfg, png_path.name))
    logger.info("report -> %s", md_path)
    return md_path


def _render_md(summary: Dict[str, Any], cfg: SwingConfig, png_name: str) -> str:
    lines: List[str] = []
    lines.append(f"# Walk-Forward — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(
        f"Universe: 26-symbol Nifty-large-cap testing universe.\n"
        f"Period: **{summary['overall_start']}** to **{summary['overall_end']}**.\n"
        f"Windows: {len(summary['windows'])} (18m train / 6m test / 6m step).\n"
        f"Starting capital: ₹{cfg.budget:,.0f} per window.\n"
    )
    lines.append("## TL;DR")
    bh = summary["baseline_buy_and_hold"]
    fd = summary["baseline_fd_7pct"]
    strat_net = summary["strategy_net_pnl"]
    strat_ret = summary["strategy_ret_pct"]
    verdict = "BEATS" if (summary["beats_buy_and_hold"] and summary["beats_fd"]) \
              else "DOES NOT BEAT"
    lines.append(
        f"Strategy net P&L (regime ON, summed across test windows): "
        f"**₹{strat_net:+,.2f}** ({strat_ret:+.2%}).\n"
        f"Buy-and-hold equal-weight Nifty EW baseline: "
        f"₹{bh['pnl_net']:+,.2f} ({bh['ret_pct']:+.2%}).\n"
        f"7% FD baseline: ₹{fd['pnl_net']:+,.2f} ({fd['ret_pct']:+.2%}).\n"
        f"\n**Verdict:** strategy {verdict} both baselines net of costs.\n"
    )
    if not (summary["beats_buy_and_hold"] and summary["beats_fd"]):
        lines.append("### Likely drivers (from trade log)")
        # Pool all regime_on per-window stats — we can't rebuild the trade
        # log here without rerunning, so we surface aggregate per-regime
        # numbers and let the reader inspect the JSON for trade-level data.
        lines.append("- Inspect the JSON report's `per_window` -> `per_vix_regime` "
                     "for regime contribution.")
        lines.append("- High skip_counters['min_profit'] across windows would "
                     "indicate cost drag eating the edge.")
        lines.append("")
    lines.append("## Per-window")
    lines.append("| window | mode | trades | net P&L | win rate | max DD |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for r in summary["per_window"]:
        lines.append(
            f"| {r['window']} | {r['mode']} | {r['trades']} | "
            f"₹{r['net_pnl']:+,.0f} | {r['win_rate']:.1%} | "
            f"₹{r['max_dd']:,.0f} |"
        )
    lines.append("")
    lines.append("## Regime ON vs OFF — same windows, same data")
    by_window_mode: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in summary["per_window"]:
        by_window_mode.setdefault(r["window"], {})[r["mode"]] = r
    lines.append("| window | net (ON) | net (OFF) | Δ | trades (ON) | trades (OFF) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for w, m in by_window_mode.items():
        on = m.get("regime_on", {})
        off = m.get("regime_off", {})
        delta = on.get("net_pnl", 0) - off.get("net_pnl", 0)
        lines.append(
            f"| {w} | ₹{on.get('net_pnl', 0):+,.0f} | "
            f"₹{off.get('net_pnl', 0):+,.0f} | ₹{delta:+,.0f} | "
            f"{on.get('trades', 0)} | {off.get('trades', 0)} |"
        )
    lines.append("")
    if Path(png_name).suffix == ".png":
        lines.append(f"![equity curve]({png_name})")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="Inclusive YYYY-MM-DD")
    p.add_argument("--end",   required=True, help="Inclusive YYYY-MM-DD")
    p.add_argument("--config",   default="config/swing_config.yaml")
    p.add_argument("--universe", default="config/universe.yaml")
    p.add_argument("--groups",   default=None,
                   help="Comma-separated; default = config/universe.yaml default_groups")
    p.add_argument("--report-dir", default="reports")
    p.add_argument("--no-postgres", action="store_true",
                   help="Force file-backed candle cache (used by the synthetic "
                        "smoke test in tests/_walkforward_smoke.py).")
    p.add_argument("--holdout-from", default=None,
                   help="YYYY-MM-DD. Drop windows whose test period starts on "
                        "or after this date so they stay pristine for the "
                        "final-exam run. Use during iterative redesign.")
    args = p.parse_args()
    groups = args.groups.split(",") if args.groups else None
    run_walkforward(
        overall_start=args.start, overall_end=args.end,
        config_path=args.config, universe_path=args.universe,
        groups=groups, report_dir=Path(args.report_dir),
        use_postgres=not args.no_postgres,
        holdout_from=args.holdout_from,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
