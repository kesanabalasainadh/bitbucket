# VERDICT — every trade idea earns a verdict

> A deterministic crypto strategy validator that **generates inspectable candidate strategies, validates
> them with rolling walk-forward + explicit costs, blends bounded sentiment context, and ships only an
> evidence-backed verdict** — or honestly says *no edge*.
> Built for **BNB HACK: AI Trading Agent Edition** (CoinMarketCap × Trust Wallet × BNB Chain).

[![Track 2](https://img.shields.io/badge/Track%202-Strategy%20Skills-F0B90B)]() · primary
[![Track 1](https://img.shields.io/badge/Track%201-Future%20Executor-lightgrey)]() · explicitly out of scope for current code

---

## The problem

AI trading demos are often one prompt, one backtest, one cherry-picked window. They look good and fail
live. **VERDICT exists to be stricter.** It treats strategy ideas as hypotheses: generate deterministic,
human-readable candidates, test them out-of-sample on rolling windows, charge explicit costs, blend
bounded sentiment context, and only endorse a setup that survives pre-registered criteria. When nothing
survives, it says so.

## What it does

1. **Signal** — reads offline reproducible market fixtures and can use CoinMarketCap MCP/REST data when
   keys are present; x402 and execution are not implemented in this codebase.
2. **Sentiment** — builds a bounded, cacheable `SentimentSnapshot` from offline/news headlines so context
   can adjust confidence without dominating price evidence.
3. **Generate** — proposes multiple candidate strategies (momentum, mean-reversion, breakout) as
   deterministic, human-readable `StrategySpec`s.
4. **Validate** — runs each through a **rolling walk-forward** backtest with an explicit cost model
   and strict **no-lookahead** discipline.
5. **Verdict** — applies a **pre-registered 3-criterion rule** (beats benchmark net of costs · positive
   in ≥60% of out-of-sample windows · Sharpe ≥ 1 & drawdown ≤ 25%) and emits an **`AgentVerdict`**: the
   best risk-adjusted strategy, or an honest `NO_TRADE`.
6. **Narrate** — runs an explainable decision matrix, kill-switch check, and personality-driven DCA
   narrative. This is not live execution.

```
Market Data ─► News/Sentiment ─► Feature Layer ─► Decision Matrix ─► Risk Gates
     └──────────── candidate StrategySpecs ─► walk-forward + cost model ─► Verdict ─► DCA Narrative
```

## Why it's different (the moat)

Most Track-2 entries: *generate → backtest once → ship.*
VERDICT: *generate candidates → walk-forward → cost-aware → sentiment-bounded matrix → risk-gated verdict.*
That rigor is ported from a production trading engine (see [`reference/legacy_nse/`](reference/legacy_nse/README.md))
and is exactly what the judging rewards: real technical execution, an original take, and credibility.

## Reproduce the StrategySpec (Track 2 — one command, clean clone)

```bash
pip install -r requirements.txt
python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h
```
That's the whole reproducibility checkpoint: **no API key, no network** — it runs on committed
historical candles under `verdict/core/_fixtures/candles/` and prints a schema-valid `AgentVerdict`
JSON. Rerun it and you get byte-identical output (bar the `created_at` timestamp); the spec's numbers
come from deterministic code, never an LLM guess. On the shipped fixtures the engine returns an honest
**`NO_TRADE`** — nothing clears the pre-registered bar after DEX costs, and that null result *is* the
deliverable's credibility.

Want the equity / benchmark / drawdown PNGs alongside the JSON (and live CMC data if you set
`CMC_MCP_API_KEY`)? Use the skill's entrypoint — same numbers, plus charts:

```bash
cp .env.example .env           # optional: add CMC_MCP_API_KEY for live regime context
python skills/verdict-strategy/scripts/run.py \
    --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h \
    --out skills/verdict-strategy/examples
```
The CMC Skill itself lives in [`skills/verdict-strategy/`](skills/verdict-strategy/SKILL.md) — `cp -r`
it into any Anthropic-compatible agent and invoke `/verdict`. Real sample outputs (JSON + curves) are
in [`skills/verdict-strategy/examples/`](skills/verdict-strategy/examples/).

For the V2 judge summary flow:

```bash
python -m verdict.demo --asset BNB/USDT --tf 4h --trait balanced
```

## Repo layout

| Path | What |
|---|---|
| `verdict/schema.py` | shared data contracts (StrategySpec, AgentVerdict, Signal, Decision, Fill) |
| `verdict/core/` | quant core — backtest, walk-forward, costs, candidates, selection (WP-1, WP-2) |
| `verdict/signals/` | CoinMarketCap adapter — MCP/REST/x402 → `Signal`/`OHLCVSeries` (WP-3) |
| `verdict/sentiment/` | bounded news/headline sentiment snapshots |
| `verdict/safety/` | kill-switch architecture and risk gate state |
| `verdict/agent/` | narrative-only DCA agent; no live execution |
| `verdict/execution/` | reserved for future executor work; currently empty |
| `skills/verdict-strategy/` | the CMC **Strategy Skill** — Track-2 deliverable (WP-2) |
| `docs/` | `HACKATHON_BRIEF.md`, `API_REFERENCE.md` |
| `agents/` | parallel-build work packages `WP-1..6` |
| `reference/legacy_nse/` | proven engine being ported (reference only) |
| `CONTRACTS.md` · `ORCHESTRATION.md` | interfaces + the build plan |

## Sponsor stack
**CoinMarketCap Agent Hub** (signal layer) is the implemented sponsor-facing path. **Trust Wallet Agent
Kit / BNB Chain / PancakeSwap execution is future work and is not claimed as working code.** Details in
[`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

## Status
🚧 Hackathon build in progress (build lock: **2026-06-21 12:00 UTC**). See
[`agents/README.md`](agents/README.md) for the live status board.

## License
MIT
