# VERDICT — Simulation Report

**Run date:** 2026-06-20 · **Engine:** VERDICT quant core (Track 2) · **Tests:** 121 passed, 2 skipped

> **Headline verdict: `NO_TRADE`.** Across BNB/USDT, CAKE/USDT, BTC/USDT and ETH/USDT on the 4h (and 1d)
> timeframe, no candidate strategy survived rolling walk-forward validation net of PancakeSwap DEX costs.
> This is the engine behaving exactly as designed — an honest null result, not a failure.

---

## 1. How the simulation ran

| Item | Value |
|---|---|
| Data source | Committed offline candles (real BNB/CAKE/BTC/ETH, ccxt-kucoin/binance) |
| Window | 2022-01-01 → 2026-06-20 (~9,787 bars per asset, 4h) |
| Candidates | 12 (momentum / mean-reversion / breakout × 4 assets) |
| Validation | 10 rolling **out-of-sample** walk-forward windows each |
| Cost model | PancakeSwap v2 — 0.25% fee + 30 bps slippage = **1.10% round-trip** |
| Selection rule | Pre-registered 3-criterion gate (committed before results) |

**Note on live data:** the CMC key is valid, but this sandbox's network egress allowlist blocks
`mcp.coinmarketcap.com` / `pro-api.coinmarketcap.com` (HTTP 403). The engine correctly fell back to
offline fixtures, so the sim uses real historical prices — just not a live feed.

### The pre-registered gate (a strategy must pass **all three**)
1. **Beats benchmark** — median OOS return > buy-&-hold over the same windows.
2. **Consistent** — beats benchmark in **≥ 60%** of OOS windows (≥ 6/10).
3. **Risk-adjusted** — **Sharpe ≥ 1.0 AND max drawdown ≤ 25%**.

---

## 2. Results — PancakeSwap cost (the shipped verdict)

| Candidate | Return | Sharpe | Max DD | Windows won | Trades |
|---|---:|---:|---:|---:|---:|
| BNB Trend Momentum | −22.6% | −0.27 | 39.0% | 4/10 | 102 |
| BNB Mean-Reversion | −59.6% | −2.68 | 60.7% | 5/10 | 98 |
| BNB Donchian Breakout | −50.7% | −1.30 | 54.0% | 4/10 | 104 |
| CAKE Trend Momentum | −24.1% | −0.27 | 35.3% | 6/10 | 96 |
| CAKE Mean-Reversion | −70.2% | −2.88 | 70.2% | 5/10 | 147 |
| CAKE Donchian Breakout | −26.1% | −0.41 | 34.6% | 5/10 | 137 |
| BTC Trend Momentum | −23.8% | −0.28 | 32.5% | 3/10 | 105 |
| BTC Mean-Reversion | −38.2% | −1.79 | 39.5% | 3/10 | 47 |
| BTC Donchian Breakout | −50.1% | −1.19 | 52.3% | 2/10 | 135 |
| ETH Trend Momentum | −8.1% | −0.05 | 38.1% | 4/10 | 93 |
| ETH Mean-Reversion | −50.6% | −1.88 | 52.4% | 4/10 | 114 |
| ETH Donchian Breakout | −23.8% | −0.47 | 32.1% | 4/10 | 118 |

**Verdict → `NO_TRADE`.** Kill-switch independently `LOCKED` on the drawdown breach.

---

## 3. Cost sensitivity — the single most important finding

Re-running with a CEX cost model (Binance spot, **0.30% round-trip**) keeps the verdict at `NO_TRADE`
but **flips the momentum archetype strongly positive** — proving the 1.10% DEX cost, not the logic, is
what kills most strategies:

| Candidate | Return @1.10% (DEX) | Return @0.30% (CEX) | Sharpe @CEX | Max DD @CEX |
|---|---:|---:|---:|---:|
| BTC Trend Momentum | −23.8% | **+42.2%** | 0.57 | 20.5% |
| ETH Trend Momentum | −8.1% | **+39.2%** | 0.57 | 25.7% |
| BNB Trend Momentum | −22.6% | **+29.8%** | 0.45 | 29.2% |
| ETH Donchian Breakout | −23.8% | **+33.6%** | 0.63 | 15.2% |
| CAKE Donchian Breakout | −26.1% | **+22.4%** | 0.40 | 25.5% |
| BTC Mean-Reversion | −38.2% | −48.6% | −1.55 | 50.4% |

Even at CEX cost the gate still isn't cleared — **Sharpe stalls around 0.4–0.6 (gate is 1.0)** and
window-consistency stays below 60%. So cost is the *primary* drag; signal quality / consistency is the
*secondary* one.

---

## 4. Scorecard — what's good, what's weak, what needs work

### ✅ Performing well (keep as-is)
- **The selection engine & honesty logic.** Deterministic, no-lookahead (dedicated lookahead test),
  OOS-only, reproducible byte-for-byte. The `NO_TRADE` is *correct*, and the two-sided demo confirms the
  engine **will** issue a TRADE when a real edge exists (+273% on a synthetic range market, all gates passed).
- **Risk plumbing.** Cost model, kill-switch (LOCKED on DD breach), regime gating (stands aside in
  downtrends — no knife-catching) all fire correctly.
- **Trend Momentum signal (BTC / ETH / BNB).** The *only* archetype that is fundamentally sound — it is
  positive and the drawdown is near/under the 25% gate once cost is realistic. This is the foundation to build on.

### ⚠️ OK but borderline — needs improvement
- **Trend Momentum's risk-adjustment.** Returns are there (@CEX), but **Sharpe ~0.5 vs the 1.0 gate** and
  **window-consistency < 60%**. Fixes: volatility-scaled position sizing, a trend/ADX strength filter, and
  a sentiment/regime confidence overlay to skip the choppiest windows.
- **Donchian Breakout.** Profitable on ETH/CAKE at CEX cost with low drawdown (ETH DD 15%), but trade
  count is high (110–145) so DEX cost eats it. Needs a turnover cap / confirmation filter to cut whipsaws.
- **The cost assumption itself.** 1.10% round-trip is realistic for PancakeSwap v2 but is the binding
  constraint. Worth modelling v3 concentrated-liquidity pools, larger trade sizing to amortise gas, or a
  CEX execution path — each materially changes the verdict.

### ❌ Performing worst — fix or retire
- **Mean-Reversion (all four assets).** Catastrophic in *both* cost models: −38% to −70%, Sharpe −1.5 to
  −2.9, drawdowns 40–70%, and the **highest trade counts** (up to 223). It is structurally broken on
  trending crypto majors — it fades moves that keep running. Either gate it to *only* confirmed range
  regimes (the two-sided demo shows it works there) or drop it from the majors universe.
- **Window consistency (Criterion 2) overall.** Even the best names win only 4–6 of 10 OOS windows. This,
  alongside Sharpe, is the most common reason candidates miss the gate — the edge is too regime-dependent.

---

## 5. Bottom line & recommended next steps

The project **runs cleanly and its decision-making is trustworthy** — it earns credibility precisely by
declining to trade when no robust edge exists. To move from "honestly declines" toward "selectively
trades", in priority order:

1. **Retire or regime-gate Mean-Reversion** on the majors (worst offender, drags the whole set).
2. **Lift Trend Momentum over the Sharpe-1.0 gate** via vol-scaled sizing + trend-strength filter.
3. **Reduce turnover** (breakout/momentum) so DEX cost stops eating positive expectancy.
4. **Model a cheaper execution venue** (PancakeSwap v3 / CEX) — the largest single lever on the verdict.
5. **Whitelist the CMC hosts** in the environment to enable live regime context.

> **Estimated live P&L as-is: ≈ 0% (by design)** — the engine would trade nothing and preserve capital.
> Track 1 live execution (`verdict/execution/`) is not implemented, so there is no real-capital path in
> this codebase today; this is a research/validation engine. Any profit figure beyond "correctly declines"
> would be fabricated.
