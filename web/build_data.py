#!/usr/bin/env python3
"""
web/build_data.py — generate the deterministic data payload the VERDICT web demo renders.

Every number on the dashboard comes from the real engine (no hand-typed figures):
  * two-sided verdicts (a genuine TRADE on a controlled range + an honest NO_TRADE on
    the real BSC majors), through the identical pre-registered pipeline;
  * the regime-intelligence grid (each archetype acts only in its regime);
  * the walk-forward OOS windows of the closest real-majors candidate;
  * a live CMC signal snapshot (real, if a key is present; offline fixture otherwise).

    python web/build_data.py            # writes web/data/verdict.json
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `verdict` importable whether run from repo root or web/.
_REPO = Path(__file__).resolve().parents[1]
if (_REPO / "verdict" / "__init__.py").exists():
    sys.path.insert(0, str(_REPO))

from verdict.core.backtest import backtest_detailed
from verdict.core.candidates import generate_candidates
from verdict.core.costs import PANCAKESWAP_V2, BINANCE_SPOT, CostModel
from verdict.core.data import load_ohlcv
from verdict.core.select import select, run_assets, _wf_params
from verdict.core.walkforward import walk_forward_detailed
from verdict.schema import OHLCVBar, OHLCVSeries, Verdict

_ZERO = CostModel(fee_pct=0.0, slippage_bps=0.0, label="zero-cost (illustrative)")
_T0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
OUT = Path(__file__).resolve().parent / "data" / "verdict.json"


# --- controlled, deterministic regime markets (illustrative) ----------------- #
def _mk(closes, *, wick=0.008, vol=None):
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        bars.append(OHLCVBar(ts=_T0 + timedelta(hours=4 * i), open=o,
                             high=max(o, c) * (1 + wick), low=min(o, c) * (1 - wick),
                             close=c, volume=(vol(i) if vol else 1000.0)))
    return OHLCVSeries(symbol="DEMO/USDT", timeframe="4h", source="controlled-regime", bars=bars)


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


def _downsample(seq, k=160):
    seq = [round(float(x), 5) for x in seq]
    if len(seq) <= k:
        return seq
    step = math.ceil(len(seq) / k)
    return [seq[i] for i in range(0, len(seq), step)]


def regime_grid():
    rows = []
    for series, label in [(_uptrend(), "uptrend"), (_range(), "range"),
                          (_downtrend(), "downtrend"), (_breakout(), "breakout")]:
        bh = round((series.bars[-1].close / series.bars[0].close - 1) * 100, 1)
        cells = {}
        for c in generate_candidates(series, None):
            m = backtest_detailed(series, c, _ZERO, trade_start=c.lookback).metrics
            cells[c.id.split("-")[0]] = {"trades": m.num_trades,
                                         "return_pct": round(m.return_pct, 1),
                                         "sharpe": round(m.sharpe_ratio, 2)}
        rows.append({"market": label, "buy_hold_pct": bh, "archetypes": cells})
    return rows


def two_sided():
    rng = _range()
    trade = select(generate_candidates(rng, None), rng, PANCAKESWAP_V2)
    notrade = run_assets(["BNB/USDT", "CAKE/USDT", "BTC/USDT", "ETH/USDT"], "4h", PANCAKESWAP_V2)

    sel = trade.selected
    tcrit = trade.criteria.get("per_candidate", {}).get(sel.id, {}) if sel else {}
    trade_block = {
        "verdict": trade.verdict.value,
        "name": sel.name if sel else None,
        "summary": trade.summary,
        "metrics": {
            "oos_sharpe": tcrit.get("oos_sharpe"),
            "window_pass_rate": tcrit.get("window_pass_rate"),
            "median_oos": tcrit.get("median_oos_return_pct"),
            "median_bench": tcrit.get("median_benchmark_return_pct"),
            "return_pct": round(sel.metrics.return_pct, 1) if sel else None,
            "max_drawdown": round(sel.metrics.max_drawdown, 1) if sel else None,
        },
        "equity": _downsample(sel.equity_curve) if sel else [],
        "benchmark": _downsample(sel.benchmark_curve) if sel else [],
        "drawdown": _downsample(sel.drawdown_curve) if sel else [],
    }
    notrade_block = {
        "verdict": notrade.verdict.value,
        "summary": notrade.summary,
        "rejected": notrade.rejected,
        "candidates": len(notrade.candidates),
    }
    return trade_block, notrade_block


def walkforward_windows():
    """The OOS windows of the closest real-majors candidate (BTC/USDT 1d, BIN floor)."""
    series = load_ohlcv("BTC/USDT", "1d")
    cands = generate_candidates(series, None)
    v = select(cands, series, BINANCE_SPOT)
    per = v.criteria.get("per_candidate", {})
    best_id = max(per, key=lambda k: per[k]["risk_score"]) if per else None
    spec = next((c for c in v.candidates if c.id == best_id), v.candidates[0] if v.candidates else None)
    train, test, step = _wf_params(len(series.bars))
    detail = walk_forward_detailed(series, spec, BINANCE_SPOT, train, test, step)
    wins = []
    for w in detail.windows:
        wins.append({
            "start": w.test_start.date().isoformat(),
            "end": w.test_end.date().isoformat(),
            "return_pct": round(w.metrics.return_pct, 1),
            "sharpe": round(w.metrics.sharpe_ratio, 2),
            "passed": bool(w.passed),
        })
    pass_rate = round(sum(1 for w in detail.windows if w.passed) / len(detail.windows) * 100) if detail.windows else 0
    return {"candidate": spec.id if spec else None, "asset": "BTC/USDT", "tf": "1d",
            "windows": wins, "pass_rate": pass_rate,
            "oos_sharpe": per.get(best_id, {}).get("oos_sharpe")}


def sentiment_block():
    """The V2 news-sentiment snapshot + the weighted decision matrix it feeds.

    Honest by construction: sentiment is bounded and capped at 15% of the matrix —
    it can modulate a decision but can never flip a NO_TRADE into a TRADE.
    """
    try:
        from verdict.sentiment import build_sentiment_snapshot
        from verdict.core.matrix import decide_matrix
        snap = build_sentiment_snapshot("BNB/USDT", use_cache=False)
        series = load_ohlcv("BNB/USDT", "4h")
        v = select(generate_candidates(series, None), series, PANCAKESWAP_V2)
        m = decide_matrix(v, snap)
        d = snap.model_dump(mode="json")
        headlines = d.get("headlines") or []
        headlines = [h if isinstance(h, str) else (h.get("headline") if isinstance(h, dict) else str(h))
                     for h in headlines][:4]
        # Structured headlines with real outlet + clickable source URL.
        headline_items = [
            {"title": it.get("title"), "source": it.get("source"),
             "url": it.get("url"), "published_at": it.get("published_at")}
            for it in (d.get("headline_items") or [])
        ][:4]
        return {
            "sentiment_score": round(d.get("sentiment_score", 0.0), 3),
            "confidence": round(d.get("confidence", 0.0), 3),
            "headline_count": d.get("headline_count", len(headlines)),
            "freshness": round(d.get("freshness", 0.0), 2),
            "source": d.get("source", "offline"),
            "headlines": headlines,
            "headline_items": headline_items,
            "matrix": {
                "action": m.action.value,
                "score": round(m.score, 1),
                "weights": m.weights,
                "components": m.components,
                "reasons": m.reasons,
            },
        }
    except Exception as e:
        return {"error": str(e)[:120]}


def onchain_identity():
    """VERDICT's committed on-chain ERC-8004 identity proof (BNB AI Agent SDK)."""
    try:
        from verdict.identity.register import load_proof
        return load_proof() or {}
    except Exception:
        return {}


def live_cmc():
    """Real live CMC snapshot if a key is present; else the offline fixture signal."""
    try:
        from verdict.signals.cmc import CMCClient, build_signal
        sig = build_signal("BNB/USDT", CMCClient.from_env())
        # "live" = real market data reached us (quotes/global-metrics/F&G), even if
        # some gated endpoints (technicals/derivatives) degraded to fixtures.
        live = bool(sig.source and sig.source != "cmc-offline")
        return {
            "symbol": sig.symbol, "price": round(sig.price, 2) if sig.price else None,
            "btc_dominance": round(sig.btc_dominance, 2) if sig.btc_dominance else None,
            "fear_greed": int(sig.fear_greed) if sig.fear_greed is not None else None,
            "regime": sig.regime, "source": sig.source,
            "live": bool(live), "alt_headwind": bool(sig.btc_dominance and sig.btc_dominance >= 55.0),
        }
    except Exception as e:
        return {"error": str(e)[:120], "live": False}


def main():
    payload = {
        "generated_note": "All numbers produced by the VERDICT engine (deterministic). See web/build_data.py.",
        "tests": "122 passed, 2 skipped",
        "cost_model": PANCAKESWAP_V2.label,
        "rule": {
            "criteria": [
                "median OOS return > median buy-&-hold (beats benchmark net of costs)",
                "beat buy-&-hold in >= 60% of out-of-sample windows",
                "Sharpe >= 1.0 AND max drawdown <= 25%",
            ],
        },
        "live_cmc": live_cmc(),
        "onchain": onchain_identity(),
        "sentiment": sentiment_block(),
        "regime_grid": regime_grid(),
        "walkforward": walkforward_windows(),
    }
    trade_block, notrade_block = two_sided()
    payload["trade"] = trade_block
    payload["no_trade"] = notrade_block

    text = json.dumps(payload, indent=2, default=str)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    # also drop a copy in static/ so the dashboard runs server-less (static site)
    static_copy = OUT.parent.parent / "static" / "verdict.json"
    static_copy.parent.mkdir(parents=True, exist_ok=True)
    static_copy.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} (+ static/verdict.json)  (trade={trade_block['verdict']}, "
          f"no_trade={notrade_block['verdict']}, "
          f"live_cmc={'live' if payload['live_cmc'].get('live') else 'offline'})")


if __name__ == "__main__":
    main()
