---
name: verdict-strategy
description: |
  Use when a user wants a *backtested* crypto trading strategy with an honest verdict — not a
  hyped one-shot backtest. VERDICT pulls live CoinMarketCap signals, generates several deterministic
  candidate strategies (momentum / mean-reversion / breakout), validates each with rolling
  walk-forward out-of-sample windows under a realistic PancakeSwap DEX cost model, applies a
  pre-registered 3-criterion rule, and emits an AgentVerdict: the best risk-adjusted StrategySpec, or
  an honest NO_TRADE when nothing survives. Every number comes from code, so the spec is reproducible.
  Trigger: /verdict, "build a backtested crypto strategy", "generate a strategy spec",
  "is there an edge on BNB", "should I trade CAKE", "honest backtest", "walk-forward a crypto strategy"
license: MIT
compatibility: ">=1.0.0"
user-invocable: true
allowed-tools:
  - mcp__cmc-mcp__get_crypto_quotes_latest
  - mcp__cmc-mcp__get_crypto_technical_analysis
  - mcp__cmc-mcp__get_global_metrics_latest
  - mcp__cmc-mcp__get_global_crypto_derivatives_metrics
---

# VERDICT — the honest crypto strategy skill

VERDICT treats strategy generation as **research, not vibes**: propose many hypotheses, test them
out-of-sample on rolling windows, charge realistic DEX costs, and endorse a strategy **only** if it
clears criteria committed *before* the results are seen. When nothing clears the bar, it says so. The
output is an `AgentVerdict` JSON — a deterministic, inspectable, backtestable `StrategySpec`, or
`NO_TRADE`.

> **Why this is different from a typical "LLM strategy" skill:** most generate one strategy, backtest
> it once on a cherry-picked window, and ship it. VERDICT adds the four things that separate quant
> research from a backtest screenshot — **(1) many candidates, (2) rolling walk-forward hold-out,
> (3) a cost-aware gate, (4) a pre-registered selection rule with an honest null result.**

---

## Prerequisites

1. **The VERDICT engine** (this skill calls it for the deterministic validation):
   ```bash
   git clone https://github.com/kesanabalasainadh/bitbucket.git
   cd bitbucket
   pip install -r requirements.txt
   ```
   The skill runs offline out of the box: committed historical candles under
   `verdict/core/_fixtures/candles/` (BNB, CAKE, BTC, ETH) make every run reproducible with **no key
   and no network**.

2. **CoinMarketCap MCP** (optional — enriches the live market regime; the engine still runs without it).
   Add to your agent's MCP config and set a key from <https://pro.coinmarketcap.com/login>:
   ```json
   {
     "mcpServers": {
       "cmc-mcp": {
         "url": "https://mcp.coinmarketcap.com/mcp",
         "headers": { "X-CMC-MCP-API-KEY": "YOUR_CMC_MCP_API_KEY" }
       }
     }
   }
   ```
   Or export `CMC_MCP_API_KEY` / `CMC_PRO_API_KEY` so `scripts/run.py` picks the live transport
   automatically. **No key → fixtures.** Secrets go in `.env` (gitignored); never commit a key.

---

## Core Principle

**Generate many, trust only walk-forward survivors, report honestly.**

- The **LLM/CMC layer** chooses the universe and the market *regime*, which tunes candidate
  parameters (risk-off tightens trend filters, deepens oversold thresholds, shrinks size).
- The **engine** does everything that decides TRADE vs NO_TRADE: no-lookahead backtest (signal on bar
  *t* close, fill at *t+1* open), rolling walk-forward, DEX cost netting, and the pre-registered rule.
- **Determinism is the contract:** identical inputs → identical `StrategySpec` numbers, byte for byte.
  The final spec's metrics come from code, **never** from a model's guess.

---

## Workflow

Run these in order. Steps 1–4 gather the live CMC market context (skip them if you have no key — the
engine falls back to committed fixtures). Step 5 produces the graded, reproducible result.

1. **Quotes** — `mcp__cmc-mcp__get_crypto_quotes_latest` for each asset (e.g. BNB, CAKE, BTC, ETH).
   Extract `quote.USD.price`. Establishes the live mark for each pair.
2. **Technicals** — `mcp__cmc-mcp__get_crypto_technical_analysis` per asset. Extract
   `rsi`, `macd`, `macd_signal`, `ema_20`, `ema_50`, `ema_100`, `atr`, `adx`. BTC's EMA(20)/EMA(50)
   feed the trend half of the regime rule.
3. **Global metrics** — `mcp__cmc-mcp__get_global_metrics_latest`. Extract **Fear & Greed** and
   **BTC dominance**. With BTC's EMA trend these set the regime: F&G ≥ 60 + uptrend → `risk_on`;
   F&G ≤ 40 + downtrend → `risk_off`; conflicting/silent → `neutral` (the rule is pre-registered in
   `verdict/signals/normalize.py`).
4. **Derivatives** — `mcp__cmc-mcp__get_global_crypto_derivatives_metrics`. Extract **funding rate**
   and **open interest**; used as a regime/quality filter and echoed into the spec's reasoning.
5. **Validate & decide** — hand the universe to the engine. It builds the `Signal` from steps 1–4
   (or fixtures), generates the candidates, walk-forward-validates them under the cost model, applies
   the pre-registered rule, and prints the `AgentVerdict` JSON:
   ```bash
   # Reproducible, offline — the canonical Track-2 command:
   python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h

   # Same result + equity/benchmark/drawdown PNGs (uses your CMC key if present):
   python skills/verdict-strategy/scripts/run.py \
       --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h \
       --out skills/verdict-strategy/examples
   ```
   Flags: `--tf 1h|4h|1d`, `--cost pancake|binance`, `--out DIR` (writes `agentverdict.json` + PNGs),
   `--json-only`.
6. **Report** — present the `AgentVerdict` to the user: the verdict, the winning spec (or the honest
   NO_TRADE), the walk-forward window pass-rate, and *why the winner won / why the others were
   rejected*. Do not soften a NO_TRADE into a TRADE — the null result is the point.

### The pre-registered rule (committed before results — auditable in `verdict/core/select.py`)

A candidate is **TRADE-eligible iff all three hold** on the out-of-sample windows:
1. **Beats benchmark net of costs** — median OOS return > median buy-&-hold over the same windows.
2. **Consistent** — beat buy-&-hold in **≥ 60%** of windows (not one lucky run).
3. **Risk-adjusted** — Sharpe **≥ 1.0** AND max drawdown **≤ 25%**.

Among passers, the highest `risk_score` (Sharpe 35% + drawdown 25% + window-consistency 25% +
win-rate 15%) wins → `TRADE`. If none pass → `NO_TRADE` with a per-candidate reason.

---

## Output Template

The skill emits exactly this shape (`verdict.schema.AgentVerdict`; full real samples in `examples/`):

```json
{
  "verdict": "TRADE | NO_TRADE",
  "selected": {
    "id": "momentum-bnbusdt-4h",
    "name": "BNB/USDT 4h Momentum Pullback",
    "assets": ["BNB/USDT"], "timeframe": "4h", "horizon": "swing (3-10 bars)",
    "indicators": ["EMA(20)", "EMA(50)", "EMA(100)", "MACD(12,26,9)", "RSI(14)", "ATR(14)"],
    "entry_rules": ["close > ema_100", "ema_20 > ema_50", "macd_hist rising", "rsi_14 in [40,65]"],
    "exit_rules": ["rsi_14 > 78", "max_hold=10 bars"],
    "stop_loss": "1.5 * ATR(14)", "take_profit": "3.0 * ATR(14)",
    "position_size": "risk 2% of equity per trade",
    "metrics": {"return_pct": 0.0, "sharpe_ratio": 0.0, "win_rate": 0.0,
                "max_drawdown": 0.0, "risk_score": 0.0, "num_trades": 0},
    "walkforward": [{"test_start": "...", "test_end": "...", "metrics": {}, "passed": true}],
    "equity_curve": [1.0], "benchmark_curve": [1.0], "drawdown_curve": [0.0],
    "reasoning": "Trend-pullback... [walk-forward: N OOS windows, beat buy&hold in X%; Sharpe ...]",
    "confidence": 0.0, "market_regime": "risk_on | risk_off | neutral",
    "cost_model": "PancakeSwap v2: 0.25% fee + 30bps slippage"
  },
  "candidates": [],
  "rejected": {"<candidate_id>": "why it was rejected"},
  "criteria": {"rule": "...", "thresholds": {}, "per_candidate": {}},
  "summary": "Plain-English verdict for the user/judges."
}
```

When `verdict` is `NO_TRADE`, `selected` is `null` and `rejected` carries a reason per candidate.

---

## Adaptation

- **Risk profile** — `risk_off` regime ⇒ candidates auto-switch to `conservative` (EMA(200) trend
  filter, deeper oversold floor, higher ADX/volume bar, 1% risk/trade); otherwise `balanced` (2%).
- **Asset / timeframe** — pass any of the committed pairs (BNB, CAKE, BTC, ETH) on `1h`, `4h`, `1d`
  (BTC/ETH ship 4h & 1d). Add more by dropping a `SYMBOL_tf.csv.gz` in the fixtures dir, or run with a
  live key to fetch fresh candles. Lower timeframes pay more in costs — the gate accounts for it.
- **Venue cost** — `--cost pancake` (default, DEX) vs `--cost binance` (CEX floor) to see how much of
  the edge is eaten by friction.

---

## Failure-Handling

The skill is built to **always return a verdict**, degrading fidelity instead of crashing:

- **No CMC key / MCP down** → use committed fixtures; the run stays fully reproducible.
- **Partial CMC data** (a tool 401s or returns a thin payload) → `build_signal` fills what it can;
  a missing block lowers `confidence`, it does not abort. The regime rule falls back to Fear & Greed
  only if BTC technicals are missing.
- **No candle fixture for a requested pair/timeframe** → that pair is listed in `rejected` with the
  reason; the other pairs still produce a verdict.
- **Nothing clears the pre-registered bar** → emit `NO_TRADE` with per-candidate reasons. This is a
  feature: an honest null beats a hyped strategy. (The shipped `examples/` are real `NO_TRADE` runs —
  on CAKE/4h the strategy *preserved* capital while buy-&-hold fell ~80%, yet still didn't clear the
  absolute risk-adjusted gate, so VERDICT declines to endorse it.)
