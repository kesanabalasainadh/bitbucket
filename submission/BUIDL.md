# VERDICT — every trade earns a verdict

**BNB HACK: AI Trading Agent Edition** (CoinMarketCap × Trust Wallet × BNB Chain) ·
**Track 2 — Strategy Skills** (primary) · Track 1 — Autonomous Agent (stretch)
**Public repo:** https://github.com/kesanabalasainadh/bitbucket

---

## TL;DR

VERDICT is an **LLM-authored crypto strategy engine that behaves like an honest quant.** It reads
CoinMarketCap signals (live with a key; reproducible committed candle fixtures otherwise), generates
several deterministic candidate strategies, validates each with **rolling walk-forward out-of-sample
windows** under a **realistic PancakeSwap DEX cost model**, and applies a **pre-registered 3-criterion
rule** to emit an `AgentVerdict`. It is **two-sided**: a genuine `TRADE` when a validated edge survives
costs, an honest **`NO_TRADE`** when none does. The deliverable is a CMC Skill
(`skills/verdict-strategy/SKILL.md`) plus the engine that backs it. **Every number comes from code, so a
judge reproduces the spec deterministically from a clean clone with no API key — byte-identical except
the `created_at` provenance timestamp.**

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
2. **Generate** — `verdict/core/candidates.py` emits **regime-gated** archetypes per asset (momentum →
   trends, mean-reversion → ranges with a confirmed turn that does not knife-catch downtrends, breakout →
   expansions) as deterministic `StrategySpec`s, using a rule grammar with primitives like `at_least N of
   [...]`, `ema_slope_N`, `bb_width`, `atr_pct`. Each archetype trades **only** in the regime where it has
   edge and stands aside elsewhere (0 trades in a downtrend). CMC Fear & Greed and **BTC dominance** tune
   risk (risk-off / BTC-dominance ≥ 55% ⇒ tighter filters, smaller size, stronger confluence for alts).
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
| Verdict | always ships a TRADE | **two-sided**: a real `TRADE` when an edge survives walk-forward + costs, an honest `NO_TRADE` (with per-candidate reasons) when none does |

## How it maps to the Track-2 judging criteria

- **Technical execution** — a real engine, not cosmetic: 122 passing tests, no-lookahead proof,
  deterministic outputs, a documented cost model, and walk-forward. `python -m pytest verdict -q` →
  **122 passed, 2 skipped**.
- **Originality** — pre-registration + a two-sided verdict is a genuinely different take: the skill
  issues a real `TRADE` when a validated edge exists *and* tells the user *not* to trade when it does
  not (see `skills/verdict-strategy/scripts/two_sided_demo.py`). That honesty is the differentiator.
- **Real-world relevance** — the output is a deterministic, inspectable, backtestable, exportable
  `StrategySpec`: exactly what a desk would diligence, and the substrate for a future live agent.
- **Demo & presentation** — one reproducible command, a clean `AgentVerdict` JSON, a regime-intelligence
  table, and equity/drawdown PNGs that make the "beat buy-&-hold?" question legible at a glance.

## Reproduce it (the judge checkpoint)

```bash
git clone https://github.com/kesanabalasainadh/bitbucket
cd bitbucket
pip install -r requirements.txt
python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h
```

No key, no network — it reads committed `ccxt-kucoin` candle fixtures and prints a schema-valid
`AgentVerdict`. On the real BSC majors it returns **`NO_TRADE`**: across BNB/CAKE/BTC/ETH on 4h, nothing
clears the pre-registered bar out-of-sample after PancakeSwap costs. But VERDICT is **two-sided** —
`python skills/verdict-strategy/scripts/two_sided_demo.py` also issues a genuine **`TRADE`** on a
controlled validated-edge regime (median OOS **+9.2%** vs buy-&-hold **+1.4%**, beat the benchmark in
**100%** of walk-forward windows), proving the skill acts when an edge survives. See real sample outputs
in `skills/verdict-strategy/examples/` (`demo_TRADE_controlled_range.json`,
`demo_NO_TRADE_real_majors.json`, `regime_intelligence.json` + curves).

## Deep CoinMarketCap usage (targets "Best Use of CMC Data & Signal")

The skill's `allowed-tools` are exactly the four CMC MCP tools it calls, each mapped to a field the
engine consumes:

- `get_crypto_quotes_latest` → live mark per pair
- `get_crypto_technical_analysis` → RSI / MACD / EMA-stack / ATR / ADX → candidate rules + regime trend
- `get_global_metrics_latest` → Fear & Greed (sets the risk-off regime) **+ BTC dominance ≥ 55%
  tightens risk and forces 3-of-3 confluence for non-BTC alts** — both consumed in `candidates.py` and
  echoed verbatim into each spec's `reasoning`
- `get_global_crypto_derivatives_metrics` → funding rate + open interest → regime/quality filter

Depth over breadth: CMC drives the *regime and parameters*; the deterministic validation runs on
committed `ccxt-kucoin` candle fixtures (CMC powers the signal/regime layer, not the raw OHLCV) so the
graded spec is reproducible. The skill degrades gracefully to offline
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

## On-chain agent identity (BNB AI Agent SDK)

VERDICT is a **registered on-chain agent**. Using the **BNB AI Agent SDK** (`bnbagent`) we minted an
**ERC-8004 agent identity** on BNB Smart Chain testnet — gas-free via the MegaFuel paymaster — so the
strategy engine has a verifiable, discoverable on-chain identity (real on-chain proof, not cosmetic):

- **agentId `1466`** · registry `0x8004a818…` · wallet `0x519556…`
- tx: <https://testnet.bscscan.com/tx/0x1d4ba443f72b84ce47e991bb7a00721acfe5b3d3518a506adfe63ea2430be8b4>
- reproduce: `python -m verdict.identity.register` (`verdict/identity/`, proof in `submission/onchain_identity.json`)

This targets the **"Best Use of BNB AI Agent SDK"** special prize, stackable with a Track-2 placement.

## Track 1 (stretch — agent layer scaffolded, live execution is future work)

The same `StrategySpec` is *designed* to feed a future BSC trading agent. What exists today: an explainable
decision matrix (`verdict/core/matrix.py` — TRADE/WAIT/DCA/NO_TRADE), a hard-drawdown **kill-switch**
(`verdict/safety/kill_switch.py`), and a sentiment-aware **DCA agent** (`verdict/agent/dca.py`) with
**zero execution authority** — it explains, it never signs. There is **no** Trust Wallet signing or
PancakeSwap *execution* in this codebase yet (`verdict/execution/` is an empty placeholder). Track 2 ships
first and stands on its own.

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
