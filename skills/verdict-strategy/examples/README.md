# Example output — real VERDICT runs

These are **actual, reproducible** outputs of the skill over the committed candle fixtures
(BNB / CAKE / BTC / ETH), not hand-written samples. Regenerate any of them with:

```bash
# 4h, all four assets (the headline run; writes the JSON + the 3 PNGs):
python skills/verdict-strategy/scripts/run.py \
    --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h \
    --out skills/verdict-strategy/examples

# 1h, BNB & CAKE (BTC/ETH ship 4h & 1d fixtures only):
python skills/verdict-strategy/scripts/run.py --assets BNB/USDT,CAKE/USDT --tf 1h --json-only
```

| File | What |
|---|---|
| `agentverdict_4h_BNB-CAKE-BTC-ETH.json` | 12 candidates (3 archetypes × 4 assets), 4h — full `AgentVerdict` |
| `agentverdict_1h_BNB-CAKE.json` | 6 candidates, 1h |
| `equity_curve.png` | strategy equity vs. buy-&-hold, for the closest candidate |
| `benchmark_curve.png` | buy-&-hold curve |
| `drawdown_curve.png` | underwater (drawdown) curve |

## The result is `NO_TRADE` — and that is the point

On these multi-year offline candles, **no candidate clears the pre-registered 3-criterion rule**
(beats benchmark net of costs · positive in ≥ 60% of OOS windows · Sharpe ≥ 1.0 & drawdown ≤ 25%),
so VERDICT returns an honest `NO_TRADE` with a per-candidate reason instead of a hyped strategy.

The PNGs plot the **closest** candidate — CAKE/USDT 4h mean-reversion. Notice the story: the strategy
(gold) ends near **0.87×** while buy-&-hold (grey) collapses to **~0.19×** — it *dodged* an ~80%
drawdown. It still fails the **absolute** risk-adjusted gate (it lost money net of costs), so the
engine **declines to endorse it**. A single-shot, cost-blind backtester would have shipped this as a
"market-beating" strategy; VERDICT's discipline is precisely that it does not.

Every number here comes from deterministic code on committed data — rerun and you get byte-identical
JSON (except the `created_at` timestamp). That reproducibility is the Track-2 deliverable.
