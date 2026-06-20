# VERDICT — every trade earns a verdict

**BNB HACK: AI Trading Agent Edition** (CoinMarketCap × Trust Wallet × BNB Chain) ·
**Track 2 — Strategy Skills** (primary) · Track 1 — Autonomous Agent (stretch)
**Public repo:** https://github.com/kesanabalasainadh/bitbucket

---

## TL;DR

VERDICT is an **LLM-authored crypto strategy engine that behaves like an honest quant.** It pulls live
CoinMarketCap signals, generates several deterministic candidate strategies, validates each with
**rolling walk-forward out-of-sample windows** under a **realistic PancakeSwap DEX cost model**, and
applies a **pre-registered 3-criterion rule** to emit an `AgentVerdict`: the best risk-adjusted
`StrategySpec`, or an honest **`NO_TRADE`** when nothing survives. The deliverable is a CMC Skill
(`skills/verdict-strategy/SKILL.md`) plus the engine that backs it. **Every number in the spec comes
from code, so a judge reproduces it byte-for-byte from a clean clone with no API key.**

---

## The problem

LLM "trading strategies" are usually one prompt, one backtest, one cherry-picked window. They look
great in a screenshot and fall apart live, because they skip the discipline real quant research
requires: out-of-sample testing, transaction costs, and a selection rule fixed *before* you see the
results. VERDICT exists to be the opposite — it endorses a strategy only when the evidence survives
that discipline, and it says "no edge" when it doesn't.

## What it does (the pipeline)

```
CoinMarketCap signal  ─►  generate many candidates  ─►  walk-forward + DEX costs  ─►  pre-registered rule  ─►  AgentVerdict JSON
  quotes / technicals       momentum · mean-reversion     rolling OOS windows,          beats benchmark ·        best spec, or
  global / derivatives       · breakout (deterministic)    no-lookahead, net of fees     ≥60% windows ·            honest NO_TRADE
                                                                                          Sharpe≥1 & DD≤25%
```

1. **Signal** — `verdict/signals/` normalizes CMC quotes, technicals, Fear & Greed / BTC dominance,
   and derivatives funding/OI into a typed `Signal`, and derives a pre-registered market `regime`.
2. **Generate** — `verdict/core/candidates.py` emits ≥ 3 distinct archetypes per asset as
   deterministic, human-readable `StrategySpec`s whose every rule is evaluable 1:1 by the backtester.
   The regime tunes parameters (risk-off ⇒ stronger trend filter, deeper oversold, smaller size).
3. **Validate** — `verdict/core/backtest.py` + `walkforward.py` run a strict **no-lookahead** backtest
   (signal on bar *t* close, fill at *t+1* open) across rolling train/test windows, netting a
   **PancakeSwap v2 cost model** (0.25% fee + 30 bps slippage) on every round trip.
4. **Verdict** — `verdict/core/select.py` applies the rule committed before results and emits the
   `AgentVerdict` (`verdict/schema.py`).

## Why it wins — the moat (vs. the reference winner)

The strongest prior Track-2 entry generated 3 candidates, **backtested once**, and shipped the best
one. VERDICT adds the four things that separate quant research from a backtest screenshot:

| | Reference one-shot entry | **VERDICT** |
|---|---|---|
| Candidates | 3, single backtest | ≥ 3 archetypes **× N assets**, each fully evidenced |
| Validation | one in-sample window | **rolling walk-forward**, strict OOS hold-out |
| Costs | none / nominal | **DEX cost model** netted on every trade + a pre-trade cost gate |
| Selection | "best risk-adjusted" post-hoc | **pre-registered 3-criterion rule** (committed before results) |
| Null result | always ships a TRADE | **honest `NO_TRADE`** with per-candidate reasons |

## How it maps to the Track-2 judging criteria

- **Technical execution** — a real engine, not cosmetic: 98 passing tests, no-lookahead proof,
  deterministic outputs, a documented cost model, and walk-forward. `pytest verdict -q` → **98 passed**.
- **Originality** — pre-registration + an honest null result is a genuinely different take: the skill
  is willing to tell the user *not* to trade. That is rare and is the credibility differentiator.
- **Real-world relevance** — the output is a deterministic, inspectable, backtestable, exportable
  `StrategySpec`: exactly what a desk would diligence, and the substrate for the Track-1 live agent.
- **Demo & presentation** — one reproducible command, a clean `AgentVerdict` JSON, and
  equity/benchmark/drawdown PNGs that make the "beat buy-&-hold?" question legible at a glance.

## Reproduce it (the judge checkpoint)

```bash
git clone https://github.com/kesanabalasainadh/bitbucket
cd bitbucket && pip install -r requirements.txt
python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h
```

No key, no network — it reads committed candles and prints a schema-valid `AgentVerdict`. On the
shipped fixtures it returns **`NO_TRADE`**: across BNB/CAKE/BTC/ETH on 4h, none of the 12 candidates
clears the pre-registered bar after PancakeSwap costs. The closest (CAKE/4h mean-reversion) *preserved*
capital while buy-&-hold fell ~80% — yet still lost money net of costs, so VERDICT **declines to
endorse it**. A single-shot backtester would have shipped it as "market-beating." See real sample
outputs (JSON + the 3 curve PNGs) in `skills/verdict-strategy/examples/`.

## Deep CoinMarketCap usage (targets "Best Use of CMC Data & Signal")

The skill's `allowed-tools` are exactly the four CMC MCP tools it calls, each mapped to a field the
engine consumes:

- `get_crypto_quotes_latest` → live mark per pair
- `get_crypto_technical_analysis` → RSI / MACD / EMA-stack / ATR / ADX → candidate rules + regime trend
- `get_global_metrics_latest` → Fear & Greed + BTC dominance → pre-registered regime rule
- `get_global_crypto_derivatives_metrics` → funding rate + open interest → regime/quality filter

Depth over breadth: CMC drives the *regime and parameters*; the deterministic validation runs on
committed candles so the graded spec is reproducible. The skill degrades gracefully to offline
fixtures when no key is present.

## Architecture / where to look

| Path | What |
|---|---|
| `skills/verdict-strategy/SKILL.md` | the Track-2 deliverable — Anthropic-format CMC Skill |
| `skills/verdict-strategy/scripts/run.py` | deterministic entrypoint (signal → candidates → select → JSON + PNGs) |
| `skills/verdict-strategy/examples/` | real sample `AgentVerdict` JSON + equity/benchmark/drawdown PNGs |
| `verdict/core/` | quant core — backtest, walk-forward, costs, candidates, **pre-registered selection** |
| `verdict/signals/` | CoinMarketCap adapter (MCP / REST / x402 / fixtures) → `Signal` |
| `verdict/schema.py` · `CONTRACTS.md` | shared data contracts (single source of truth) |

## Honesty & determinism (the pre-registered rule)

A candidate is TRADE-eligible **iff all three hold** on the out-of-sample windows, committed before
any results were seen (auditable in `verdict/core/select.py`):
1. median OOS return > median buy-&-hold (beats benchmark net of costs),
2. beat buy-&-hold in ≥ 60% of windows (consistency, not one lucky run),
3. Sharpe ≥ 1.0 **and** max drawdown ≤ 25% (risk-adjusted).

Among passers, the highest `risk_score` wins; if none pass, `NO_TRADE`. No RNG, no clock, no network in
the backtest — identical inputs give identical specs.

## Track 1 (stretch, built on the same brain)

The same `StrategySpec` feeds a live BSC agent (`verdict/agent/`, `verdict/execution/`) that signs via
the Trust Wallet Agent Kit and trades on PancakeSwap under a hard drawdown kill-switch and a risk
governor. Track 2 ships first and stands on its own.

## Tech & sponsor stack

Python · pydantic v2 · pandas / numpy · matplotlib · `ta` · ccxt (historical candles).
**CoinMarketCap Agent Hub** (signal layer) · Trust Wallet Agent Kit + BNB Chain / PancakeSwap (Track 1).

## Team & contact

- Team: VERDICT — *(2 contributors)*
- Contact (Telegram / email): _to be completed on the DoraHacks BUIDL form before submission._

## Compliance

No token launch, no fundraising, no sale of any asset is part of this project — it is a research and
tooling submission, consistent with the hackathon rules.

## License

MIT.
