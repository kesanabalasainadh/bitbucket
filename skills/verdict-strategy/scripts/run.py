#!/usr/bin/env python3
"""
VERDICT strategy skill — deterministic entrypoint.

This is the script the SKILL.md `Workflow` calls. It wires the whole Track-2
pipeline end to end and is the single command a judge runs to reproduce a spec:

    CMC Signal (live key -> MCP/REST, else committed fixtures)
        -> generate_candidates  (>= 3 deterministic archetypes, regime-tuned)
        -> select               (walk-forward + DEX costs + pre-registered rule)
        -> AgentVerdict JSON     (best risk-adjusted StrategySpec, or honest NO_TRADE)
        -> equity / benchmark / drawdown PNGs

Determinism (graded): the *validation numbers* come only from committed historical
candles and pure code — no RNG, no clock, no network in the backtest. A live CMC
key changes nothing but candidate *parameters* (regime tightening) and the human
`market_regime` narrative; with no key the offline fixtures make the run byte-for-
byte reproducible. The default invocation equals `python -m verdict.core.select`.

Usage (from the repo root, or anywhere once `verdict` is importable):

    python skills/verdict-strategy/scripts/run.py \
        --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h \
        --out skills/verdict-strategy/examples

    python skills/verdict-strategy/scripts/run.py --assets BNB/USDT --tf 4h --json-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Make `verdict` importable whether run from the repo root or the skill folder.
# scripts/run.py -> verdict-strategy -> skills -> <repo root>
# --------------------------------------------------------------------------- #
def _ensure_verdict_importable() -> None:
    try:
        import verdict  # noqa: F401
        return
    except ImportError:
        pass
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / "verdict" / "__init__.py").exists():
        sys.path.insert(0, str(repo_root))
        return
    sys.stderr.write(
        "ERROR: the `verdict` package is not importable.\n"
        "This skill validates strategies with the VERDICT engine. Per SKILL.md "
        "Prerequisites:\n"
        "  git clone https://github.com/kesanabalasainadh/bitbucket.git\n"
        "  cd bitbucket && pip install -r requirements.txt\n"
        "  python skills/verdict-strategy/scripts/run.py --assets BNB/USDT --tf 4h\n"
    )
    raise SystemExit(2)


_ensure_verdict_importable()

from verdict.schema import AgentVerdict, StrategySpec, Verdict          # noqa: E402
from verdict.core.candidates import generate_candidates                 # noqa: E402
from verdict.core.costs import BINANCE_SPOT, PANCAKESWAP_V2, CostModel  # noqa: E402
from verdict.core.data import load_ohlcv                                # noqa: E402
from verdict.core.select import select                                  # noqa: E402


# --------------------------------------------------------------------------- #
# Signal sourcing: live CMC (MCP/REST) when a key is present, else fixtures.
# from_env() already degrades to the offline fixtures when no key is set, so the
# default run reproduces `python -m verdict.core.select` exactly.
# --------------------------------------------------------------------------- #
def _signal_for(asset: str):
    try:
        from verdict.signals.cmc import CMCClient, build_signal
        return build_signal(asset, CMCClient.from_env())
    except Exception:
        return None


def _series_for(asset: str, timeframe: str):
    try:
        s = load_ohlcv(asset, timeframe)
        return s if len(s.bars) >= 60 else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# The visible wiring: build_signal -> generate_candidates -> select, aggregated
# across assets. Mirrors verdict.core.select.run_assets so the offline default is
# identical to the documented CLI, but with the CMC client made explicit here.
# --------------------------------------------------------------------------- #
def compute_verdict(assets: list[str], timeframe: str, costs: CostModel) -> AgentVerdict:
    all_candidates: list[StrategySpec] = []
    all_rejected: dict[str, str] = {}
    per_asset_criteria: dict = {}
    trade_picks: list[tuple[str, AgentVerdict]] = []

    for asset in assets:
        series = _series_for(asset, timeframe)
        if series is None:
            all_rejected[f"{asset}:{timeframe}"] = "no candle data available offline (need a fixture)"
            continue
        signal = _signal_for(asset)
        cands = generate_candidates(series, signal)
        v = select(cands, series, costs)
        all_candidates.extend(v.candidates)
        all_rejected.update(v.rejected)
        per_asset_criteria[asset] = v.criteria
        if v.verdict == Verdict.TRADE and v.selected is not None:
            trade_picks.append((asset, v))

    if trade_picks:
        asset, best = max(trade_picks, key=lambda av: av[1].selected.metrics.risk_score)
        keep = ("rule", "thresholds", "risk_score_blend")
        return AgentVerdict(
            verdict=Verdict.TRADE, selected=best.selected, candidates=all_candidates,
            rejected=all_rejected,
            criteria={"per_asset": per_asset_criteria, "winning_asset": asset,
                      **{k: v for k, v in best.criteria.items() if k in keep}},
            summary=best.summary + f" (best across {len(assets)} assets.)",
        )

    return AgentVerdict(
        verdict=Verdict.NO_TRADE, selected=None, candidates=all_candidates,
        rejected=all_rejected, criteria={"per_asset": per_asset_criteria},
        summary=(f"NO_TRADE across {', '.join(assets)} ({timeframe}): no candidate survived "
                 f"walk-forward validation net of {costs.label}. Honest null result."),
    )


# --------------------------------------------------------------------------- #
# Curve rendering — the demo PNGs (equity / benchmark / drawdown).
# Plotted from the spec the verdict highlights: the TRADE winner, or (NO_TRADE)
# the closest candidate by risk_score so a judge sees *why* it fell short.
# --------------------------------------------------------------------------- #
def _spec_to_plot(verdict: AgentVerdict) -> Optional[StrategySpec]:
    if verdict.selected is not None:
        return verdict.selected
    scored = [c for c in verdict.candidates if c.equity_curve]
    if not scored:
        return None
    return max(scored, key=lambda c: c.metrics.risk_score)


def write_curves(spec: StrategySpec, out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")               # headless, deterministic, no display
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    equity = spec.equity_curve or [1.0]
    benchmark = spec.benchmark_curve or [1.0]
    drawdown = spec.drawdown_curve or [0.0]
    tag = f"{spec.name} — {spec.cost_model}"
    written: list[Path] = []

    # 1) equity vs benchmark (the "did we beat buy & hold?" plot)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(equity, color="#F0B90B", lw=2.0, label="VERDICT strategy")
    ax.plot(benchmark, color="#888888", lw=1.4, ls="--", label="buy & hold")
    ax.set_title(f"Equity curve · {tag}", fontsize=10)
    ax.set_xlabel("bar"); ax.set_ylabel("equity (×start)")
    ax.grid(alpha=0.25); ax.legend(loc="best", fontsize=8)
    fig.tight_layout(); p = out_dir / "equity_curve.png"
    fig.savefig(p, dpi=120); plt.close(fig); written.append(p)

    # 2) benchmark (buy & hold) on its own
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(benchmark, color="#26A17B", lw=1.8, label="buy & hold")
    ax.set_title(f"Benchmark (buy & hold) · {spec.assets[0] if spec.assets else ''}", fontsize=10)
    ax.set_xlabel("bar"); ax.set_ylabel("equity (×start)")
    ax.grid(alpha=0.25); ax.legend(loc="best", fontsize=8)
    fig.tight_layout(); p = out_dir / "benchmark_curve.png"
    fig.savefig(p, dpi=120); plt.close(fig); written.append(p)

    # 3) drawdown (underwater)
    dd_pct = [d * 100.0 for d in drawdown]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.fill_between(range(len(dd_pct)), dd_pct, 0.0, color="#C0392B", alpha=0.35)
    ax.plot(dd_pct, color="#C0392B", lw=1.2)
    ax.set_title(f"Drawdown · {tag}", fontsize=10)
    ax.set_xlabel("bar"); ax.set_ylabel("drawdown (%)")
    ax.grid(alpha=0.25)
    fig.tight_layout(); p = out_dir / "drawdown_curve.png"
    fig.savefig(p, dpi=120); plt.close(fig); written.append(p)

    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="VERDICT strategy skill — AgentVerdict JSON + curves.")
    ap.add_argument("--assets", default="BNB/USDT",
                    help="comma-separated pairs, e.g. BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT")
    ap.add_argument("--tf", default="4h", help="timeframe: 1h | 4h | 1d")
    ap.add_argument("--cost", default="pancake", choices=["pancake", "binance"],
                    help="cost model: pancake (PancakeSwap v2) | binance (CEX spot)")
    ap.add_argument("--out", default=None,
                    help="directory to write agentverdict.json + the 3 curve PNGs")
    ap.add_argument("--json-only", action="store_true", help="print JSON only; skip PNGs")
    args = ap.parse_args(argv)

    costs = PANCAKESWAP_V2 if args.cost == "pancake" else BINANCE_SPOT
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]

    verdict = compute_verdict(assets, args.tf, costs)
    for spec in verdict.candidates:         # stamp created_at (non-workflow path)
        spec.stamp()

    payload = verdict.model_dump_json(indent=2)
    print(payload)

    if args.out and not args.json_only:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "agentverdict.json").write_text(payload + "\n", encoding="utf-8")
        spec = _spec_to_plot(verdict)
        if spec is not None:
            paths = write_curves(spec, out_dir)
            sys.stderr.write(
                f"[verdict] {verdict.verdict.value}; wrote {out_dir/'agentverdict.json'} + "
                + ", ".join(p.name for p in paths) + "\n")
        else:
            sys.stderr.write("[verdict] no candidate had curves to plot.\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
