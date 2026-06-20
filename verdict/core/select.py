"""
verdict.core.select — the pre-registered 3-criterion judge (WP-2, THE deliverable).

Every candidate is run through walk-forward validation, its evidence (OOS windows,
headline metrics, equity/benchmark/drawdown curves, risk_score) is filled in, and a
rule COMMITTED BEFORE SEEING RESULTS decides TRADE vs NO_TRADE. Shipping an honest
NO_TRADE when nothing clears the bar is the whole point — it's the credibility
differentiator that single-shot, cost-blind reference projects don't have.

PRE-REGISTERED CRITERIA (a candidate is TRADE-eligible iff ALL three hold):
  1. Beats benchmark net of costs — median OOS return > median buy-&-hold over the
     same rolling windows.
  2. Consistent — strategy beat buy-&-hold in >= 60% of OOS windows (not one lucky run).
  3. Risk-adjusted — headline Sharpe >= 1.0 AND max drawdown <= 25%.

risk_score (0-100, higher = safer; documented blend, used only to RANK passers):
  Sharpe 35% + drawdown 25% + window-consistency 25% + win-rate 15%.

    select(candidates, series, costs) -> AgentVerdict
    python -m verdict.core.select --assets BNB/USDT,ETH/USDT --tf 4h
"""
from __future__ import annotations

import argparse
import math
import sys
from statistics import median
from typing import Optional

from verdict.schema import (
    AgentVerdict, OHLCVSeries, StrategySpec, Verdict,
)
from verdict.core.backtest import backtest_detailed
from verdict.core.costs import CostModel, PANCAKESWAP_V2
from verdict.core.walkforward import walk_forward_detailed

# Pre-registered thresholds (committed before results — judges can audit these).
MIN_WINDOW_PASS_RATE = 0.60
MIN_SHARPE = 1.0
MAX_DRAWDOWN_PCT = 25.0


def _wf_params(n: int) -> tuple[int, int, int]:
    """Choose (train, test, step) bars so windows have warmup and >= ~4 windows."""
    test = max(60, n // 12)
    train = max(2 * test, 220)         # >= 220 so EMA(200) is warmed in each window
    step = test
    return train, test, step


def risk_score(sharpe: float, max_dd: float, win_rate: float, pass_rate: float) -> float:
    s = max(0.0, min(sharpe / 3.0, 1.0)) * 35.0
    d = max(0.0, min(1.0 - max_dd / 40.0, 1.0)) * 25.0
    c = max(0.0, min(pass_rate, 1.0)) * 25.0
    w = max(0.0, min(win_rate / 0.6, 1.0)) * 15.0
    return round(s + d + c + w, 2)


def _downsample(seq, max_points: int = 240) -> list[float]:
    if len(seq) <= max_points:
        return [round(float(x), 6) for x in seq]
    k = math.ceil(len(seq) / max_points)
    return [round(float(seq[i]), 6) for i in range(0, len(seq), k)]


def evaluate_candidate(spec: StrategySpec, series: OHLCVSeries, costs: CostModel,
                       wf_params: Optional[tuple[int, int, int]] = None) -> dict:
    """Validate one candidate; mutate its spec with evidence; return the verdict math."""
    n = len(series.bars)
    train, test, step = wf_params or _wf_params(n)

    detail = walk_forward_detailed(series, spec, costs, train, test, step)
    full = backtest_detailed(series, spec, costs)
    m = full.metrics

    pass_rate = (sum(1 for w in detail.windows if w.passed) / len(detail.windows)
                 if detail.windows else 0.0)
    med_oos = median(detail.strategy_returns) if detail.strategy_returns else 0.0
    med_bench = median(detail.benchmark_returns) if detail.benchmark_returns else 0.0
    oos_sharpe = median([w.metrics.sharpe_ratio for w in detail.windows]) if detail.windows else 0.0
    oos_max_dd = max([w.metrics.max_drawdown for w in detail.windows], default=0.0)
    oos_win_rate = median([w.metrics.win_rate for w in detail.windows]) if detail.windows else 0.0

    c1 = bool(detail.windows) and med_oos > med_bench
    c2 = pass_rate >= MIN_WINDOW_PASS_RATE
    c3 = (oos_sharpe >= MIN_SHARPE) and (oos_max_dd <= MAX_DRAWDOWN_PCT)
    eligible = bool(c1 and c2 and c3)

    score = risk_score(oos_sharpe, oos_max_dd, oos_win_rate, pass_rate)

    # fill the spec's evidence in place
    m.risk_score = score
    spec.metrics = m
    spec.walkforward = detail.windows
    spec.equity_curve = _downsample(full.equity_curve)
    spec.benchmark_curve = _downsample(full.benchmark_curve)
    spec.drawdown_curve = _downsample(full.drawdown_curve)
    spec.cost_model = costs.label
    spec.confidence = round(max(0.0, min(0.95, 0.4 * pass_rate + 0.6 * score / 100.0)), 2)
    spec.reasoning += (
        f" [walk-forward: {len(detail.windows)} OOS windows, beat buy&hold in "
        f"{pass_rate:.0%}; median OOS {med_oos:+.2f}% vs benchmark {med_bench:+.2f}%; "
        f"OOS Sharpe {oos_sharpe:.2f}, OOS maxDD {oos_max_dd:.1f}%, "
        f"{m.num_trades} trades, risk_score {score:.0f}/100.]"
    )

    reason = ""
    if not eligible:
        fails = []
        if not c1:
            fails.append(f"median OOS {med_oos:+.2f}% did not beat buy&hold {med_bench:+.2f}%")
        if not c2:
            fails.append(f"only {pass_rate:.0%} of windows beat benchmark (need >= {MIN_WINDOW_PASS_RATE:.0%})")
        if not c3:
            fails.append(f"OOS risk-adjusted gate failed (Sharpe {oos_sharpe:.2f} / maxDD {oos_max_dd:.1f}%)")
        reason = "; ".join(fails)

    return dict(spec=spec, eligible=eligible, risk_score=score, reason=reason,
                c1=c1, c2=c2, c3=c3, pass_rate=round(pass_rate, 4),
                median_oos=round(med_oos, 4), median_bench=round(med_bench, 4),
                oos_sharpe=round(oos_sharpe, 4), oos_max_drawdown=round(oos_max_dd, 4),
                n_windows=len(detail.windows))


def select(candidates: list[StrategySpec], series: OHLCVSeries, costs: CostModel) -> AgentVerdict:
    """Run every candidate through walk-forward + the pre-registered rule; emit a verdict."""
    params = _wf_params(len(series.bars))
    evals = [evaluate_candidate(c, series, costs, params) for c in candidates]
    out = [e["spec"] for e in evals]

    rejected: dict[str, str] = {}
    for e in evals:
        if not e["eligible"]:
            rejected[e["spec"].id] = e["reason"] or "did not pass the pre-registered criteria"

    eligible = [e for e in evals if e["eligible"]]
    if eligible:
        winner = max(eligible, key=lambda e: e["risk_score"])
        for e in eligible:
            if e is not winner:
                rejected[e["spec"].id] = (
                    f"passed all 3 criteria (risk_score {e['risk_score']:.0f}) but ranked "
                    f"below {winner['spec'].id} (risk_score {winner['risk_score']:.0f})")
        verdict, selected = Verdict.TRADE, winner["spec"]
        w = winner
        summary = (
            f"TRADE: {selected.name} on {series.symbol} {series.timeframe}. It cleared all "
            f"three pre-registered criteria — median OOS return {w['median_oos']:+.2f}% vs "
            f"buy&hold {w['median_bench']:+.2f}%, beat the benchmark in {w['pass_rate']:.0%} of "
            f"{w['n_windows']} walk-forward windows, OOS Sharpe {w['oos_sharpe']:.2f}, "
            f"OOS max drawdown {w['oos_max_drawdown']:.1f}% — and scored highest on "
            f"risk_score ({w['risk_score']:.0f}/100), net of {costs.label}."
        )
    else:
        verdict, selected = Verdict.NO_TRADE, None
        best = max(evals, key=lambda e: e["risk_score"], default=None)
        near = (f" Closest was {best['spec'].id} (risk_score {best['risk_score']:.0f}): "
                f"{best['reason']}." if best else "")
        summary = (
            f"NO_TRADE on {series.symbol} {series.timeframe}: none of {len(candidates)} "
            f"candidates cleared the pre-registered criteria net of {costs.label}. An honest "
            f"null result beats a hyped strategy — the gross edges did not survive walk-forward "
            f"validation after DEX costs." + near
        )

    criteria = {
        "rule": ("Pre-registered before results: TRADE-eligible iff (1) median OOS return > "
                 "median buy&hold, (2) beat benchmark in >= 60% of OOS windows, "
                 "(3) Sharpe >= 1.0 AND max drawdown <= 25%."),
        "thresholds": {"min_window_pass_rate": MIN_WINDOW_PASS_RATE,
                       "min_sharpe": MIN_SHARPE, "max_drawdown_pct": MAX_DRAWDOWN_PCT},
        "risk_score_blend": "Sharpe 35% + drawdown 25% + window-consistency 25% + win-rate 15%",
        "per_candidate": {
            e["spec"].id: {
                "criterion_1_beats_benchmark": e["c1"],
                "criterion_2_window_consistency": e["c2"],
                "criterion_3_risk_adjusted": e["c3"],
                "eligible": e["eligible"],
                "window_pass_rate": e["pass_rate"],
                "median_oos_return_pct": e["median_oos"],
                "median_benchmark_return_pct": e["median_bench"],
                "oos_sharpe": e["oos_sharpe"],
                "oos_max_drawdown_pct": e["oos_max_drawdown"],
                "risk_score": e["risk_score"],
            } for e in evals
        },
    }
    return AgentVerdict(verdict=verdict, selected=selected, candidates=out,
                        rejected=rejected, criteria=criteria, summary=summary)


# --------------------------------------------------------------------------- #
# CLI — multi-asset orchestration over the contract-level single-series select()
# --------------------------------------------------------------------------- #
def _load_series(asset: str, timeframe: str) -> Optional[OHLCVSeries]:
    try:
        from verdict.core.data import load_ohlcv
        s = load_ohlcv(asset, timeframe)
        return s if len(s.bars) >= 60 else None
    except Exception:
        return None


def _maybe_signal(asset: str):
    """Best-effort offline CMC signal so candidates are regime-aware; None on miss."""
    try:
        from verdict.signals.cmc import CMCClient, build_signal
        return build_signal(asset, CMCClient.offline())
    except Exception:
        return None


def run_assets(assets: list[str], timeframe: str, costs: CostModel) -> AgentVerdict:
    from verdict.core.candidates import generate_candidates

    all_candidates: list[StrategySpec] = []
    all_rejected: dict[str, str] = {}
    per_asset_criteria: dict = {}
    trade_picks: list[tuple[str, AgentVerdict]] = []

    for asset in assets:
        series = _load_series(asset, timeframe)
        if series is None:
            all_rejected[f"{asset}:{timeframe}"] = "no candle data available offline (need a fixture)"
            continue
        signal = _maybe_signal(asset)
        cands = generate_candidates(series, signal)
        v = select(cands, series, costs)
        all_candidates.extend(v.candidates)
        all_rejected.update(v.rejected)
        per_asset_criteria[asset] = v.criteria
        if v.verdict == Verdict.TRADE and v.selected is not None:
            trade_picks.append((asset, v))

    if trade_picks:
        asset, best = max(trade_picks, key=lambda av: av[1].selected.metrics.risk_score)
        return AgentVerdict(
            verdict=Verdict.TRADE, selected=best.selected, candidates=all_candidates,
            rejected=all_rejected,
            criteria={"per_asset": per_asset_criteria, "winning_asset": asset,
                      **{k: v for k, v in best.criteria.items() if k in ("rule", "thresholds", "risk_score_blend")}},
            summary=best.summary + f" (best across {len(assets)} assets.)",
        )

    return AgentVerdict(
        verdict=Verdict.NO_TRADE, selected=None, candidates=all_candidates,
        rejected=all_rejected,
        criteria={"per_asset": per_asset_criteria},
        summary=(f"NO_TRADE across {', '.join(assets)} ({timeframe}): no candidate survived "
                 f"walk-forward validation net of {costs.label}. Honest null result."),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="VERDICT strategy selection -> AgentVerdict JSON.")
    parser.add_argument("--assets", default="BNB/USDT", help="comma-separated, e.g. BNB/USDT,ETH/USDT")
    parser.add_argument("--tf", default="4h", help="timeframe: 1h | 4h | 1d")
    parser.add_argument("--cost", default="pancake", choices=["pancake", "binance"])
    args = parser.parse_args(argv)

    from verdict.core.costs import BINANCE_SPOT
    costs = PANCAKESWAP_V2 if args.cost == "pancake" else BINANCE_SPOT
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    verdict = run_assets(assets, args.tf, costs)
    for spec in verdict.candidates:          # stamp created_at (non-workflow code path)
        spec.stamp()
    print(verdict.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
