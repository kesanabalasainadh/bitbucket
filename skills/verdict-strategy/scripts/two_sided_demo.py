#!/usr/bin/env python3
"""
VERDICT — the two-sided demo: proof the engine knows WHEN to act.

The standard critique of an "honest NO_TRADE" skill is "does it ever actually
produce a strategy?". This script answers that through the SAME pre-registered,
walk-forward, cost-netted pipeline used everywhere else:

  1. REGIME INTELLIGENCE — on deterministic controlled markets, each archetype
     trades ONLY in the regime where it has edge and STANDS ASIDE elsewhere
     (the headline: mean-reversion takes zero trades in a downtrend — no knife-
     catching).
  2. TRADE — on a controlled RANGE market where a robust edge genuinely exists,
     the engine clears all three pre-registered criteria and emits a TRADE.
  3. NO_TRADE — on the real BSC-relevant majors (BNB/CAKE/BTC/ETH), net of
     PancakeSwap DEX costs, nothing clears the bar out-of-sample, so it honestly
     declines.

Everything is deterministic (RNG-free synthetic markets + committed candle
fixtures) and runs with NO API key and NO network. The controlled markets are
clearly-labelled illustrations of regimes; the real verdict is the honest one.

    python skills/verdict-strategy/scripts/two_sided_demo.py
    python skills/verdict-strategy/scripts/two_sided_demo.py --out skills/verdict-strategy/examples
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _ensure_verdict_importable() -> None:
    try:
        import verdict  # noqa: F401
        return
    except ImportError:
        repo_root = Path(__file__).resolve().parents[3]
        if (repo_root / "verdict" / "__init__.py").exists():
            sys.path.insert(0, str(repo_root))
            return
        raise


_ensure_verdict_importable()

from verdict.core.backtest import backtest_detailed                # noqa: E402
from verdict.core.candidates import generate_candidates            # noqa: E402
from verdict.core.costs import BINANCE_SPOT, CostModel, PANCAKESWAP_V2  # noqa: E402
from verdict.core.data import load_ohlcv                           # noqa: E402
from verdict.core.select import run_assets, select                 # noqa: E402
from verdict.schema import OHLCVBar, OHLCVSeries, Verdict          # noqa: E402

_ZERO = CostModel(fee_pct=0.0, slippage_bps=0.0, label="zero-cost (illustrative)")
_T0 = datetime(2023, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Deterministic, RNG-free controlled markets (illustrative regimes)
# --------------------------------------------------------------------------- #
def _mk(closes, *, wick: float = 0.008, vol=None, symbol="DEMO/USDT") -> OHLCVSeries:
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        v = vol(i) if vol else 1000.0
        bars.append(OHLCVBar(ts=_T0 + timedelta(hours=4 * i), open=o,
                             high=max(o, c) * (1 + wick), low=min(o, c) * (1 - wick),
                             close=c, volume=v))
    return OHLCVSeries(symbol=symbol, timeframe="4h", source="controlled-regime", bars=bars)


def _uptrend(n=1400):
    return _mk([100 * (1.004 ** i) * (1 + 0.012 * math.sin(i / 4)) for i in range(n)])


def _range(n=1400):
    return _mk([100 * (1 + 0.05 * math.sin(i * 1.1) + 0.05 * math.sin(i * 0.37)) for i in range(n)])


def _downtrend(n=1400):
    return _mk([100 * (0.996 ** i) * (1 + 0.03 * math.sin(i / 9)) for i in range(n)])


def _breakout(n=1400):
    closes, lvl = [], 100.0
    for i in range(n):
        if i % 120 < 90:
            closes.append(lvl * (1 + 0.004 * math.sin(i)))
        else:
            lvl *= 1.01
            closes.append(lvl)
    return _mk(closes, vol=lambda i: 5000.0 if i % 120 >= 90 else 1000.0)


# --------------------------------------------------------------------------- #
# Curve rendering (reuses the spec's committed curves)
# --------------------------------------------------------------------------- #
def _write_curves(spec, out_dir: Path, tag: str) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    equity = spec.equity_curve or [1.0]
    benchmark = spec.benchmark_curve or [1.0]
    drawdown = [d * 100.0 for d in (spec.drawdown_curve or [0.0])]
    written = []

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(equity, color="#F0B90B", lw=2.0, label="VERDICT strategy")
    ax.plot(benchmark, color="#888888", lw=1.4, ls="--", label="buy & hold")
    ax.set_title(f"Equity — {tag} · {spec.name}", fontsize=10)
    ax.set_xlabel("bar"); ax.set_ylabel("equity (x start)")
    ax.grid(alpha=0.25); ax.legend(loc="best", fontsize=8)
    fig.tight_layout(); p = out_dir / f"{tag}_equity.png"
    fig.savefig(p, dpi=120); plt.close(fig); written.append(p)

    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.fill_between(range(len(drawdown)), drawdown, 0.0, color="#C0392B", alpha=0.35)
    ax.plot(drawdown, color="#C0392B", lw=1.2)
    ax.set_title(f"Drawdown — {tag} · {spec.name}", fontsize=10)
    ax.set_xlabel("bar"); ax.set_ylabel("drawdown (%)")
    ax.grid(alpha=0.25)
    fig.tight_layout(); p = out_dir / f"{tag}_drawdown.png"
    fig.savefig(p, dpi=120); plt.close(fig); written.append(p)
    return written


# --------------------------------------------------------------------------- #
# The demo
# --------------------------------------------------------------------------- #
def regime_intelligence() -> list[dict]:
    """Each archetype acts only in its regime; meanrev stands aside in a downtrend."""
    rows = []
    for series, label, expect in [
        (_uptrend(), "uptrend", "momentum acts"),
        (_range(), "range", "mean-reversion acts"),
        (_downtrend(), "downtrend", "ALL stand aside (no knife-catch)"),
        (_breakout(), "breakout", "breakout acts"),
    ]:
        per = {}
        for c in generate_candidates(series, None):
            m = backtest_detailed(series, c, _ZERO, trade_start=c.lookback).metrics
            per[c.id.split("-")[0]] = {"trades": m.num_trades,
                                       "return_pct": round(m.return_pct, 1),
                                       "sharpe": round(m.sharpe_ratio, 2)}
        rows.append({"market": label, "expectation": expect, "archetypes": per})
    return rows


def two_verdicts(costs: CostModel):
    trade = select(generate_candidates(_range(), None), _range(), costs)
    notrade = run_assets(["BNB/USDT", "CAKE/USDT", "BTC/USDT", "ETH/USDT"], "4h", costs)
    return trade, notrade


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="VERDICT two-sided demo (TRADE + NO_TRADE).")
    ap.add_argument("--cost", default="pancake", choices=["pancake", "binance"])
    ap.add_argument("--out", default=None, help="dir to write demo AgentVerdict JSON + curves")
    args = ap.parse_args(argv)
    costs = PANCAKESWAP_V2 if args.cost == "pancake" else BINANCE_SPOT

    regimes = regime_intelligence()
    trade, notrade = two_verdicts(costs)

    print("=" * 76)
    print("VERDICT — TWO-SIDED DEMO  (it knows WHEN to act)   net of:", costs.label)
    print("=" * 76)
    print("\n1) REGIME INTELLIGENCE (controlled markets, illustrative):")
    print(f"   {'market':10} {'momentum':>16} {'meanrev':>16} {'breakout':>16}   expectation")
    for r in regimes:
        def fmt(k):
            a = r["archetypes"].get(k)
            return f"{a['trades']}t {a['return_pct']:+.0f}%" if a else "-"
        print(f"   {r['market']:10} {fmt('momentum'):>16} {fmt('meanrev'):>16} "
              f"{fmt('breakout'):>16}   [{r['expectation']}]")

    print("\n2) TRADE — controlled range (a regime where a validated edge exists):")
    if trade.selected:
        s = trade.selected
        print(f"   {trade.verdict.value}: {s.name} | OOS-validated, net of {costs.label}")
        print(f"   {trade.summary[:200]}")
    else:
        print(f"   {trade.verdict.value}")

    print("\n3) NO_TRADE — the real BSC majors (BNB/CAKE/BTC/ETH, 4h):")
    print(f"   {notrade.verdict.value}: {notrade.summary[:200]}")

    print("\nVERDICT issues a TRADE when (and only when) a robust edge survives "
          "walk-forward\nvalidation net of DEX costs; otherwise it honestly declines. "
          "Both verdicts come\nfrom the identical pre-registered pipeline.")

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for spec in list(trade.candidates) + list(notrade.candidates):
            spec.stamp()
        (out_dir / "demo_TRADE_controlled_range.json").write_text(
            trade.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (out_dir / "demo_NO_TRADE_real_majors.json").write_text(
            notrade.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (out_dir / "regime_intelligence.json").write_text(
            json.dumps(regimes, indent=2) + "\n", encoding="utf-8")
        paths = []
        if trade.selected:
            paths = _write_curves(trade.selected, out_dir, "TRADE")
        sys.stderr.write(f"[two-sided demo] wrote {out_dir}/demo_*.json + "
                         + ", ".join(p.name for p in paths) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
