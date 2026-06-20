from __future__ import annotations

import argparse
import json
from datetime import timezone
from typing import Optional

from verdict.agent import AgentTrait, narrate_dca
from verdict.core.costs import PANCAKESWAP_V2
from verdict.core.data import load_ohlcv
from verdict.core.matrix import decide_matrix
from verdict.core.select import select
from verdict.core.candidates import generate_candidates
from verdict.safety import evaluate_kill_switch
from verdict.sentiment import build_sentiment_snapshot
from verdict.signals.cmc import CMCClient, build_signal


def _signal(asset: str):
    try:
        return build_signal(asset, CMCClient.offline())
    except Exception:
        return None


def run_demo(asset: str, timeframe: str, trait: AgentTrait) -> dict:
    series = load_ohlcv(asset, timeframe)
    sentiment = build_sentiment_snapshot(asset, now=series.bars[-1].ts.astimezone(timezone.utc), use_cache=False)
    candidates = generate_candidates(series, _signal(asset))
    verdict = select(candidates, series, PANCAKESWAP_V2)
    best = verdict.selected or max(verdict.candidates, key=lambda c: c.metrics.risk_score)
    cost_pct = PANCAKESWAP_V2.round_trip_cost_frac(10_000.0) * 100.0
    kill = evaluate_kill_switch(
        max_drawdown_pct=best.metrics.max_drawdown,
        sentiment=sentiment,
        data_ts=series.bars[-1].ts,
        round_trip_cost_pct=cost_pct,
        now=series.bars[-1].ts.astimezone(timezone.utc),
    )
    matrix = decide_matrix(verdict, sentiment, risk_blocked=kill.triggered != [])
    narrative = narrate_dca(matrix, sentiment, kill, trait=trait)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "market_data": {
            "bars": len(series.bars),
            "start": series.bars[0].ts.isoformat() if series.bars else None,
            "end": series.bars[-1].ts.isoformat() if series.bars else None,
            "source": series.source,
        },
        "sentiment": sentiment.model_dump(mode="json", exclude={"headlines", "headline_items"}),
        "strategy": {
            "candidates": len(verdict.candidates),
            "best_candidate": best.id,
            "core_verdict": verdict.verdict.value,
            "risk_score": best.metrics.risk_score,
            "return_pct": best.metrics.return_pct,
            "max_drawdown": best.metrics.max_drawdown,
        },
        "decision_matrix": matrix.model_dump(mode="json"),
        "kill_switch": kill.model_dump(mode="json"),
        "dca_agent": narrative.model_dump(mode="json"),
        "scope": "Track-2 narrative and research demo only; no live execution.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="VERDICT V2 judge demo summary.")
    parser.add_argument("--asset", default="BNB/USDT")
    parser.add_argument("--tf", default="4h")
    parser.add_argument("--trait", choices=[t.value for t in AgentTrait], default=AgentTrait.BALANCED.value)
    args = parser.parse_args(argv)
    print(json.dumps(run_demo(args.asset, args.tf, AgentTrait(args.trait)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
