# Example output — VERDICT is two-sided (it knows *when* to act)

These are **real, reproducible** outputs of the engine — not hand-written samples.
Regenerate all of them deterministically (no key, no network) with:

```bash
python skills/verdict-strategy/scripts/two_sided_demo.py --out skills/verdict-strategy/examples
```

The common critique of an honest "NO_TRADE" skill is *"does it ever actually produce
a strategy?"* These artifacts answer it — through the **same** pre-registered,
walk-forward, cost-netted pipeline:

| File | What it shows |
|---|---|
| `regime_intelligence.json` | Each archetype trades **only** in the regime where it has edge and **stands aside** elsewhere — incl. **0 trades in a downtrend** (the knife-catch fix). |
| `demo_TRADE_controlled_range.json` | A genuine **`TRADE`** verdict: on a regime where a robust edge exists, mean-reversion clears all three pre-registered criteria (median OOS **+9.2%** vs buy&hold **+1.4%**, beat the benchmark in **100%** of walk-forward windows), net of PancakeSwap costs. |
| `demo_NO_TRADE_real_majors.json` | An honest **`NO_TRADE`** on the real BSC majors (BNB/CAKE/BTC/ETH, 4h): out-of-sample, net of DEX costs, nothing clears the bar. |
| `TRADE_equity.png` / `TRADE_drawdown.png` | The TRADE winner's equity (vs buy&hold) and drawdown. |

## The story
1. **Regime intelligence** — VERDICT routes each archetype to the regime where it has
   edge (momentum → trends, mean-reversion → ranges, breakout → expansions) and
   **refuses to trade** the wrong regime. Most retail strategies blow up by
   mean-reverting a downtrend; VERDICT takes **zero** trades there.
2. **It issues a TRADE when warranted** — given a regime with a real, walk-forward-
   validated, cost-surviving edge, the engine emits a `TRADE` with full evidence
   (windows, curves, the per-criterion audit).
3. **It declines when there's no edge** — on the actual majors, net of DEX costs,
   no candidate clears all three out-of-sample criteria, so it returns `NO_TRADE`.
   A single-shot, cost-blind backtester would have shipped a loser as "market-beating."

Every number is deterministic code on committed/controlled data — rerun and you get
the same verdicts (only the `created_at` provenance timestamp differs). The
controlled-regime markets are clearly-labelled, RNG-free illustrations; the verdict
on the real majors is the honest one.
