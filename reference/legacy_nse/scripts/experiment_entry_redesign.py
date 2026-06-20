#!/usr/bin/env python3
"""
Entry-redesign pre-registered experiment (2026-06-11).

Reads the pre-registration in ``experiments/2026-06-11_entry_redesign.md``,
runs the 5 entries × 2 exits = 10-cell grid, applies the pre-committed
3-criterion selection rule, emits results.

Data window: 2021-01-01 → 2024-12-31. Holdout 2025+ untouched.
Capital: ₹1,00,000 per window. Regime gate: ON.

Exits are FIXED carries from commit 2de09b9 (exit experiment):
  Exit-A: stale_trade_days=0, max_hold_days=20
  Exit-D: Exit-A + sl_atr_mult=1.0

Selection rule (all three required):
  (a) Net-positive in ≥ 4 of 5 train windows.
  (b) Median window net ≥ ₹3,500.
  (c) 2024-H2 window net ≥ −₹500.
Statistical hygiene: cells averaging < 8 trades/window are flagged
"insufficient sample" and CANNOT win regardless of P&L.

Output:
    experiments/2026-06-11_entry_redesign_results.md
    experiments/2026-06-11_entry_redesign_results.json
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from src.backtest.regime import RegimeConfig
from src.backtest.swing_backtester import SwingBacktester, SwingConfig
from src.data.candle_cache import CandleCache
from src.strategy.entry_variants import make_generator
from src.utils.universe import filter_by_liquidity, load_universe

from scripts.run_walkforward import (
    daily_to_ticks, load_candles_for, load_series, make_windows,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("entry_experiment")


# ---------------------------------------------------------------------------
# Pre-committed parameters
# ---------------------------------------------------------------------------

OVERALL_START = "2021-01-01"
OVERALL_END = "2024-12-31"
HOLDOUT_FROM = "2025-01-01"
CAPITAL = 100_000.0
ENTRIES = ["E0", "E1", "E2", "E3", "E4"]
EXITS = ["A", "D"]

CRITERION_B_MIN_MEDIAN = 3_500.0   # FD floor
CRITERION_C_MIN_2024H2 = -500.0    # near-flat
CRITERION_A_MIN_POSITIVE_FRACTION = 4 / 5
MIN_TRADES_PER_WINDOW_FOR_WIN = 8


def _baseline_cfg(yaml_path: str = "config/swing_config.yaml") -> SwingConfig:
    return dataclasses.replace(
        SwingConfig.from_yaml(yaml_path), budget=CAPITAL,
    )


def _exit_overrides(exit_code: str, base: SwingConfig) -> SwingConfig:
    if exit_code == "A":
        return dataclasses.replace(base, stale_trade_days=0, max_hold_days=20)
    if exit_code == "D":
        return dataclasses.replace(
            base, stale_trade_days=0, max_hold_days=20, sl_atr_mult=1.0,
        )
    raise ValueError(f"unknown exit code {exit_code!r}")


# ---------------------------------------------------------------------------
# Per-window result
# ---------------------------------------------------------------------------

@dataclass
class WindowResult:
    window: str
    trades: int
    gross: float
    charges: float
    net: float
    win_rate: float
    avg_win: float
    avg_loss: float
    avg_holding_days: float


@dataclass
class CellResult:
    entry: str
    exit_: str
    windows: List[WindowResult] = field(default_factory=list)
    filter_rejections: Dict[str, int] = field(default_factory=dict)
    per_group: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.entry}/{self.exit_}"

    @property
    def total_net(self) -> float:
        return sum(w.net for w in self.windows)

    @property
    def total_gross(self) -> float:
        return sum(w.gross for w in self.windows)

    @property
    def total_charges(self) -> float:
        return sum(w.charges for w in self.windows)

    @property
    def total_trades(self) -> int:
        return sum(w.trades for w in self.windows)

    @property
    def positive_windows(self) -> int:
        return sum(1 for w in self.windows if w.net > 0)

    @property
    def median_window_net(self) -> float:
        return statistics.median([w.net for w in self.windows]) if self.windows else 0.0

    @property
    def trades_per_window(self) -> float:
        return self.total_trades / len(self.windows) if self.windows else 0.0

    @property
    def window_2024h2_net(self) -> float:
        for w in self.windows:
            if "2024-07-01_to_2024-12-31" in w.window:
                return w.net
        return 0.0

    @property
    def gross_per_trade(self) -> float:
        return self.total_gross / max(self.total_trades, 1)

    @property
    def cost_per_trade(self) -> float:
        return self.total_charges / max(self.total_trades, 1)

    @property
    def win_rate(self) -> float:
        n = sum(w.trades for w in self.windows)
        if n == 0:
            return 0.0
        weighted = sum(w.win_rate * w.trades for w in self.windows)
        return weighted / n

    @property
    def weighted_win_loss(self) -> float:
        num = 0.0
        den = 0
        for w in self.windows:
            if w.avg_loss < 0:
                num += abs(w.avg_win / w.avg_loss) * w.trades
                den += w.trades
        return num / den if den else float("inf")

    @property
    def avg_hold(self) -> float:
        n = sum(w.trades for w in self.windows)
        if n == 0:
            return 0.0
        return sum(w.avg_holding_days * w.trades for w in self.windows) / n

    def insufficient_sample(self) -> bool:
        return self.trades_per_window < MIN_TRADES_PER_WINDOW_FOR_WIN

    def criteria_pass(self) -> Dict[str, bool]:
        return {
            "a_positive_windows": self.positive_windows >= 4,
            "b_median_floor": self.median_window_net >= CRITERION_B_MIN_MEDIAN,
            "c_2024h2": self.window_2024h2_net >= CRITERION_C_MIN_2024H2,
            "hygiene_trades_per_window": not self.insufficient_sample(),
        }

    def passes_all(self) -> bool:
        return all(self.criteria_pass().values())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cell(
    entry: str, exit_code: str, base_cfg: SwingConfig,
    windows, universe, sym_keys, s2g,
    all_daily, vix, nifty,
) -> CellResult:
    cfg = _exit_overrides(exit_code, base_cfg)
    res = CellResult(entry=entry, exit_=exit_code)
    group_acc: Dict[str, Dict[str, float]] = {}

    for w in windows:
        if w.test_start >= HOLDOUT_FROM:
            continue
        liquid = filter_by_liquidity(
            sym_keys.keys(), all_daily, w.train_end,
            floor_inr=universe.liquidity_floor_inr,
        )
        wdata = {
            s: all_daily[s].loc[w.train_start:w.test_end]
            for s in liquid if s in all_daily
        }
        if not wdata:
            continue
        ticks = daily_to_ticks(wdata)

        bt = SwingBacktester(
            cfg,
            vix_series=vix, nifty_series=nifty,
            regime_config=RegimeConfig(enabled=True),
            symbol_to_group=s2g,
        )
        # Swap the generator for the entry variant. nifty_series is needed
        # only for E2 but harmless to pass everywhere.
        bt.signal_gen = make_generator(
            entry, cfg.strategy_dict(), nifty_series=nifty,
        )

        report = bt.run(ticks)

        test_trades = [
            t for t in report.trade_log
            if w.test_start <= t.get("exit_date", "") <= w.test_end
        ]
        net = sum(t["pnl"] for t in test_trades)
        gross = sum(t.get("gross_pnl", 0.0) for t in test_trades)
        charges = sum(t.get("charges", 0.0) for t in test_trades)
        wins = [t["pnl"] for t in test_trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in test_trades if t["pnl"] <= 0]
        wr = (len(wins) / len(test_trades)) if test_trades else 0.0
        aw = (sum(wins) / len(wins)) if wins else 0.0
        al = (sum(losses) / len(losses)) if losses else 0.0
        hold = [t.get("days_held", 0) for t in test_trades]
        avgh = (sum(hold) / len(hold)) if hold else 0.0

        res.windows.append(WindowResult(
            window=w.label, trades=len(test_trades),
            gross=round(gross, 2), charges=round(charges, 2),
            net=round(net, 2), win_rate=round(wr, 4),
            avg_win=round(aw, 2), avg_loss=round(al, 2),
            avg_holding_days=round(avgh, 2),
        ))

        # Filter-rejection counts (E1 / E2 / E3 / E4 only — E0 has none)
        gen_rej = getattr(bt.signal_gen, "rejected", None)
        if gen_rej:
            for k, v in gen_rej.items():
                res.filter_rejections[k] = res.filter_rejections.get(k, 0) + int(v)

        # Aggregate per-group totals across windows (for the top cell only)
        for t in test_trades:
            grp = t.get("entry_group", "?")
            g = group_acc.setdefault(grp, {"trades": 0, "pnl": 0.0, "wins": 0})
            g["trades"] += 1
            g["pnl"] += t.get("pnl", 0.0)
            if t.get("pnl", 0.0) > 0:
                g["wins"] += 1

        logger.info(
            "[%s/%s] %s: trades=%d net=%s gross=%s costs=%s",
            entry, exit_code, w.label, len(test_trades),
            f"Rs {net:+,.0f}", f"Rs {gross:+,.0f}", f"Rs {charges:,.0f}",
        )

    for g, v in group_acc.items():
        v["pnl"] = round(v["pnl"], 2)
        v["win_rate"] = round(v["wins"] / v["trades"], 4) if v["trades"] else 0.0
    res.per_group = group_acc
    return res


# ---------------------------------------------------------------------------
# Selection rule
# ---------------------------------------------------------------------------

def select_winner(cells: List[CellResult]
                  ) -> Tuple[Optional[CellResult], List[CellResult], str]:
    """Return (winner_or_None, ranked_passers, prose)."""
    passers = [c for c in cells if c.passes_all()]
    if not passers:
        return None, [], (
            "**No cell passed all three criteria.** Per the pre-registered "
            "plan, the verdict is: this strategy family cannot beat an FD "
            "after costs. The redesign loop **stops**. No E5 is proposed; "
            "no criterion is softened. Await direction."
        )
    passers.sort(key=lambda c: c.median_window_net, reverse=True)
    winner = passers[0]
    if len(passers) == 1:
        prose = (
            f"**Winner: cell {winner.label}.** "
            f"Passed all three criteria; sole passer in the grid."
        )
    else:
        runners = ", ".join(c.label for c in passers[1:])
        prose = (
            f"**Winner: cell {winner.label}** (ranked by median window net "
            f"₹{winner.median_window_net:+,.0f}). "
            f"Runners-up (also passing all three): {runners}."
        )
    return winner, passers, prose


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_md(cells: List[CellResult], winner: Optional[CellResult],
              passers: List[CellResult], verdict_prose: str) -> str:
    parts: List[str] = []
    parts.append("# Entry-Redesign Experiment — Results")
    parts.append("")
    parts.append(f"Run: **{datetime.now().strftime('%Y-%m-%d %H:%M')}**")
    parts.append(f"Data window: **{OVERALL_START}** → **{OVERALL_END}** (5 train windows). 2025+ untouched.")
    parts.append(f"Capital per window: ₹{int(CAPITAL):,}. Regime: ON. Universe: 26 symbols.")
    parts.append(f"Pre-registration: see `experiments/2026-06-11_entry_redesign.md` (committed 21d8b87, before any code or run).")
    parts.append("")

    # First sentence per spec: if results are bad, say so.
    if winner is None:
        first = (
            "**Honest summary:** No cell passed all three pre-committed "
            "criteria. The current EMA-pullback signal family — and the "
            "two breakout variants — cannot generate a swing system that "
            "beats a 7 % FD net of costs on this universe. The redesign "
            "loop stops here per the pre-registration."
        )
    elif winner is not None:
        first = (
            f"**Honest summary:** Cell {winner.label} passed all three "
            f"pre-committed criteria with median window net "
            f"₹{winner.median_window_net:+,.0f}, "
            f"net-positive in {winner.positive_windows} of 5 windows, "
            f"2024-H2 net ₹{winner.window_2024h2_net:+,.0f}, "
            f"and average {winner.trades_per_window:.1f} trades / window."
        )
    parts.append(first)
    parts.append("")

    # Per-cell diagnosis table (full)
    parts.append("## All 10 cells — full diagnosis")
    parts.append("")
    parts.append(
        "| cell | trades | net (₹) | gross (₹) | charges (₹) | "
        "gross/trade | cost/trade | win:loss | win rate | avg hold (d) | "
        "+windows/5 | median win net (₹) | 2024-H2 (₹) | trades/window |"
    )
    parts.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for c in cells:
        flag = " ⚠️ thin" if c.insufficient_sample() else ""
        parts.append(
            f"| {c.label}{flag} | {c.total_trades} | "
            f"{c.total_net:+,.0f} | {c.total_gross:+,.0f} | "
            f"{c.total_charges:,.0f} | "
            f"{c.gross_per_trade:+,.1f} | {c.cost_per_trade:,.1f} | "
            f"{c.weighted_win_loss:.2f}× | {c.win_rate*100:.1f}% | "
            f"{c.avg_hold:.1f} | "
            f"{c.positive_windows}/5 | "
            f"{c.median_window_net:+,.0f} | "
            f"{c.window_2024h2_net:+,.0f} | "
            f"{c.trades_per_window:.1f} |"
        )
    parts.append("")

    # Criteria pass/fail
    parts.append("## Three-criterion pass/fail")
    parts.append("")
    parts.append(
        "| cell | (a) ≥4/5 positive | (b) median ≥ ₹3,500 | "
        "(c) 2024-H2 ≥ −₹500 | hygiene ≥ 8 trades/win | passes all? |"
    )
    parts.append("|---|---|---|---|---|---|")
    for c in cells:
        cr = c.criteria_pass()
        check = lambda b: "✓" if b else "✗"
        passes_all = all(cr.values())
        parts.append(
            f"| {c.label} | "
            f"{check(cr['a_positive_windows'])} ({c.positive_windows}/5) | "
            f"{check(cr['b_median_floor'])} (₹{c.median_window_net:+,.0f}) | "
            f"{check(cr['c_2024h2'])} (₹{c.window_2024h2_net:+,.0f}) | "
            f"{check(cr['hygiene_trades_per_window'])} ({c.trades_per_window:.1f}) | "
            f"{'**✓**' if passes_all else '✗'} |"
        )
    parts.append("")

    # Per-window net P&L grid
    win_labels = [w.window for w in cells[0].windows] if cells and cells[0].windows else []
    if win_labels:
        parts.append("## Per-window net P&L (₹)")
        parts.append("")
        parts.append("| cell | " + " | ".join(win_labels) + " |")
        parts.append("|---|" + "---:|" * len(win_labels))
        for c in cells:
            row = []
            window_by_name = {w.window: w for w in c.windows}
            for lbl in win_labels:
                w = window_by_name.get(lbl)
                row.append(f"{w.net:+,.0f}" if w else "—")
            parts.append(f"| {c.label} | " + " | ".join(row) + " |")
        parts.append("")

    # Filter rejection counts
    parts.append("## Filter-rejection counts")
    parts.append("")
    parts.append("How many candidate entries each new filter refused, "
                  "summed across all windows.")
    parts.append("")
    parts.append("| cell | rejection counters |")
    parts.append("|---|---|")
    for c in cells:
        if not c.filter_rejections:
            parts.append(f"| {c.label} | _(no filter-specific rejections — E0 / baseline)_ |")
        else:
            kvs = ", ".join(f"`{k}={v}`" for k, v in sorted(c.filter_rejections.items()))
            parts.append(f"| {c.label} | {kvs} |")
    parts.append("")

    # Selection-rule evaluation
    parts.append("## Selection-rule evaluation")
    parts.append("")
    parts.append(verdict_prose)
    parts.append("")

    # Per-group (top cell only, if a winner)
    if winner is not None and winner.per_group:
        parts.append(f"## Per-group net P&L — top cell {winner.label}")
        parts.append("")
        parts.append("| group | trades | net (₹) | wins | win rate |")
        parts.append("|---|---:|---:|---:|---:|")
        rows = sorted(winner.per_group.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
        for grp, v in rows:
            parts.append(
                f"| `{grp}` | {int(v['trades'])} | {v['pnl']:+,.0f} | "
                f"{int(v['wins'])} | {v['win_rate']*100:.1f}% |"
            )
        parts.append("")

    # Discipline self-check
    parts.append("## Discipline self-check")
    parts.append("")
    parts.append(
        f"- Data window: {OVERALL_START} → {OVERALL_END}. ✓\n"
        f"- Holdout enforced: every cell skips windows whose test "
        f"period starts on/after {HOLDOUT_FROM}. ✓\n"
        f"- Grid: 5 entries × 2 exits, pre-committed in "
        f"`experiments/2026-06-11_entry_redesign.md` (commit 21d8b87). ✓\n"
        f"- Selection rule applied exactly as written. ✓\n"
        f"- Holdout 2025+ untouched. ✓\n"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    universe = load_universe("config/universe.yaml", strict=False)
    sym_keys = universe.symbol_to_instrument_key
    s2g = universe.symbol_to_group
    logger.info("universe: %d symbols", len(sym_keys))

    cache = CandleCache()
    try:
        all_daily = load_candles_for(cache, sym_keys, OVERALL_START, OVERALL_END)
        vix = load_series(cache, "NSE_INDEX|India VIX", OVERALL_START, OVERALL_END)
        nifty = load_series(cache, "NSE_INDEX|Nifty 50", OVERALL_START, OVERALL_END)
    finally:
        cache.close()

    if not all_daily:
        raise SystemExit(
            f"No candle data. Run scripts/fetch_historical.py "
            f"--start {OVERALL_START} --end {OVERALL_END} --indices first."
        )

    windows = make_windows(OVERALL_START, OVERALL_END)
    windows = [w for w in windows if w.test_start < HOLDOUT_FROM]
    logger.info("running %d windows: %s",
                 len(windows), ", ".join(w.label for w in windows))

    base = _baseline_cfg()
    cells: List[CellResult] = []
    for entry in ENTRIES:
        for exit_code in EXITS:
            logger.info("== running cell %s/%s ==", entry, exit_code)
            cells.append(run_cell(
                entry, exit_code, base, windows,
                universe, sym_keys, s2g, all_daily, vix, nifty,
            ))

    winner, passers, prose = select_winner(cells)

    md = render_md(cells, winner, passers, prose)
    out_md = Path("experiments/2026-06-11_entry_redesign_results.md")
    out_json = Path("experiments/2026-06-11_entry_redesign_results.json")
    out_md.write_text(md)
    out_json.write_text(json.dumps({
        "overall_start": OVERALL_START, "overall_end": OVERALL_END,
        "holdout_from": HOLDOUT_FROM, "capital": CAPITAL,
        "windows": [w.label for w in windows],
        "criteria": {
            "a_min_positive_windows": 4,
            "b_min_median_net": CRITERION_B_MIN_MEDIAN,
            "c_min_2024h2_net": CRITERION_C_MIN_2024H2,
            "hygiene_min_trades_per_window": MIN_TRADES_PER_WINDOW_FOR_WIN,
        },
        "winner": winner.label if winner else None,
        "passers": [p.label for p in passers],
        "verdict": prose,
        "cells": [
            {
                "entry": c.entry, "exit": c.exit_, "label": c.label,
                "total_net": c.total_net, "total_gross": c.total_gross,
                "total_charges": c.total_charges, "total_trades": c.total_trades,
                "positive_windows": c.positive_windows,
                "median_window_net": c.median_window_net,
                "window_2024h2_net": c.window_2024h2_net,
                "gross_per_trade": c.gross_per_trade,
                "cost_per_trade": c.cost_per_trade,
                "win_rate": c.win_rate,
                "weighted_win_loss": c.weighted_win_loss,
                "avg_hold": c.avg_hold,
                "trades_per_window": c.trades_per_window,
                "filter_rejections": c.filter_rejections,
                "per_group": c.per_group,
                "windows": [dataclasses.asdict(w) for w in c.windows],
                "criteria_pass": c.criteria_pass(),
                "passes_all": c.passes_all(),
            }
            for c in cells
        ],
    }, indent=2, default=str))
    logger.info("results -> %s", out_md)
    print()
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
