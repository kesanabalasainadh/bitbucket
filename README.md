# VERDICT — every trade earns a verdict

> An LLM-authored crypto strategy engine that **generates many candidate strategies, validates them with
> rolling walk-forward + realistic DEX costs, and ships only what survives** — or honestly says *no edge*.
> Built for **BNB HACK: AI Trading Agent Edition** (CoinMarketCap × Trust Wallet × BNB Chain).

[![Track 2](https://img.shields.io/badge/Track%202-Strategy%20Skills-F0B90B)]() · primary
[![Track 1](https://img.shields.io/badge/Track%201-Autonomous%20Agent-26A17B)]() · stretch

---

## The problem

LLM "trading strategies" are usually one prompt, one backtest, one cherry-picked window. They look great
and fail live. **VERDICT exists to be the opposite: an honest quant.** It treats strategy generation as
research — propose many hypotheses, test them out-of-sample on rolling windows, charge realistic costs,
and only endorse a strategy that survives pre-registered criteria. When nothing survives, it says so.

## What it does

1. **Signal** — pulls live crypto market data from the **CoinMarketCap Agent Hub** (quotes, technicals,
   derivatives funding/OI, Fear & Greed, narratives) over MCP / REST / x402.
2. **Generate** — proposes multiple candidate strategies (momentum, mean-reversion, breakout) as
   deterministic, human-readable `StrategySpec`s.
3. **Validate** — runs each through a **rolling walk-forward** backtest with a **DEX cost model**
   (PancakeSwap fees + slippage) and strict **no-lookahead** discipline.
4. **Verdict** — applies a **pre-registered 3-criterion rule** (beats benchmark net of costs · positive
   in ≥60% of out-of-sample windows · Sharpe ≥ 1 & drawdown ≤ 25%) and emits an **`AgentVerdict`**: the
   best risk-adjusted strategy, or an honest `NO_TRADE`.
5. **Execute** *(Track 1, stretch)* — hands the chosen spec to a live agent that signs via the **Trust
   Wallet Agent Kit** and trades on **PancakeSwap / BSC**, governed by a hard drawdown kill-switch.

```
CoinMarketCap ─► Signal ─► candidate StrategySpecs ─► walk-forward + cost model ─► AgentVerdict ─► JSON
   (data)                                                    (the moat)              │
                                                                                     └► Trust Wallet ─► BSC  (Track 1)
```

## Why it's different (the moat)

Most Track-2 entries: *generate → backtest once → ship.*
VERDICT: *generate many → walk-forward → cost-aware → pre-registered selection → honest verdict.*
That rigor is ported from a production trading engine (see [`reference/legacy_nse/`](reference/legacy_nse/README.md))
and is exactly what the judging rewards: real technical execution, an original take, and credibility.

## Quickstart (Track 2 — reproduce the StrategySpec)

```bash
pip install -r requirements.txt
cp .env.example .env           # add CMC_MCP_API_KEY (or run keyless via ccxt + x402)
python -m verdict.core.select --assets BNB/USDT,ETH/USDT --tf 4h    # prints an AgentVerdict JSON
```
The CMC Skill wrapper lives in [`skills/verdict-strategy/`](skills/verdict-strategy/) — `cp -r` it into
any Anthropic-compatible agent and invoke `/verdict`.

## Repo layout

| Path | What |
|---|---|
| `verdict/schema.py` | shared data contracts (StrategySpec, AgentVerdict, Signal, Decision, Fill) |
| `verdict/core/` | quant core — backtest, walk-forward, costs, candidates, selection (WP-1, WP-2) |
| `verdict/signals/` | CoinMarketCap adapter — MCP/REST/x402 → `Signal`/`OHLCVSeries` (WP-3) |
| `verdict/execution/` | Trust Wallet / PancakeSwap executors (WP-4, Track 1) |
| `verdict/agent/` | live runtime loop + risk governor (WP-5, Track 1) |
| `skills/verdict-strategy/` | the CMC **Strategy Skill** — Track-2 deliverable (WP-2) |
| `docs/` | `HACKATHON_BRIEF.md`, `API_REFERENCE.md` |
| `agents/` | parallel-build work packages `WP-1..6` |
| `reference/legacy_nse/` | proven engine being ported (reference only) |
| `CONTRACTS.md` · `ORCHESTRATION.md` | interfaces + the build plan |

## Sponsor stack
**CoinMarketCap Agent Hub** (signal layer, all tracks) · **Trust Wallet Agent Kit** (custody+execution,
Track 1) · **BNB Chain / PancakeSwap** (venue, Track 1). Details in
[`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

## Status
🚧 Hackathon build in progress (build lock: **2026-06-21 12:00 UTC**). See
[`agents/README.md`](agents/README.md) for the live status board.

## License
MIT
