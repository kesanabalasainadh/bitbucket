# WP-1 — Quant Core (Track 2 critical path)

**You own:** `verdict/core/` · **Branch:** `wp-1-quant-core` · **Blocks:** WP-2.
**Goal:** port the migrated NSE engine into an **asset-agnostic crypto backtest + walk-forward engine**
that turns an `OHLCVSeries` + a `StrategySpec` into honest `StrategyMetrics` and `WalkForwardWindow`s.

## Why you matter
VERDICT's entire credibility is your engine. Most Track-2 teams backtest once on one window. You give
us **rolling walk-forward, realistic DEX costs, and no-lookahead discipline** — the moat. The strategy
doesn't have to win; the *evaluation* has to be unimpeachable.

## Read first
`docs/HACKATHON_BRIEF.md` (§6/§7), `CONTRACTS.md` (your signatures + the 3 criteria), `verdict/schema.py`.

## Reference to port (in `reference/legacy_nse/`)
- `src/backtest/swing_backtester.py` — the no-lookahead day-by-day loop (signal@close, fill@next open),
  ATR sizing, SL/target/stale/max-hold + trailing/partial exits. **This is your template.**
- `src/backtest/cost_model.py` — `target_clears_costs()` entry-quality gate. Keep the structure, swap
  NSE charges (STT/DP/GST/SEBI) for **DEX fees + slippage**.
- `src/backtest/regime.py` — tiered context gate. Repoint India-VIX/Nifty → **BTC trend / funding rate**.
- `scripts/run_walkforward.py` + `scripts/diagnose_walkforward.py` — rolling train/test/step, hold-out,
  baselines (buy&hold, "FD" → for crypto use a **stablecoin/HODL** baseline), md/json/png reporting.
- `src/indicators/technical.py` — pure EMA/RSI/MACD/ATR/ADX. Reuse directly (or swap to the `ta` lib).

## Tasks
1. **`verdict/core/data.py`** — `load_ohlcv(symbol, timeframe, start, end, source)`. For now implement
   `source="ccxt"` (Binance public OHLCV via `ccxt`) returning an `OHLCVSeries`. Leave a `source="cmc"`
   hook that WP-3's `CMCClient.ohlcv()` will fill. Cache to parquet (port `candle_cache.py` shape).
2. **`verdict/core/indicators.py`** — thin wrapper exposing the indicators the rules need (reuse legacy
   `technical.py` or `ta`). Pure functions on a DataFrame.
3. **`verdict/core/costs.py`** — `CostModel` for crypto: `round_trip_cost(notional)` = taker/LP fee
   (e.g. PancakeSwap v2 0.25%) + configurable slippage bps + optional gas; `clears_costs(profit, notional, k)`.
4. **`verdict/core/backtest.py`** — `backtest(series, spec, costs) -> StrategyMetrics`. STRICT no-lookahead:
   evaluate rules on bar *t* close, fill at *t+1* open. Apply stop/target/max-hold from the spec. Net out
   costs every round trip. Compute return_pct, sharpe, win_rate, max_drawdown, num_trades, profit_factor.
   Also return the per-bar equity series (for curves) — expose via a small dataclass or out-param.
5. **`verdict/core/walkforward.py`** — `walk_forward(series, spec, costs, train_bars, test_bars, step_bars)`
   → `list[WalkForwardWindow]`. Mark `passed` per the per-window bar in CONTRACTS §criteria.
6. **`verdict/core/curves.py`** — `equity_drawdown(...)` → `(equity, benchmark, drawdown)` lists for the spec.
7. **Tests** `verdict/core/tests/` — synthetic-series unit tests: a known uptrend yields positive return;
   a lookahead probe (shuffle future bars) must NOT change past decisions; cost gate rejects thin edges.

## Acceptance (Checkpoint 2)
- `pytest verdict/core` green.
- `python -m verdict.core.backtest --demo` (add a tiny CLI) prints `StrategyMetrics` JSON from real
  BNB/USDT 4h candles pulled via ccxt. Walk-forward returns ≥3 windows with `passed` flags.

## Gotchas
- Crypto is **24/7** — no NSE holiday/day-of-week gating; drop `nse_holidays`, Mon/Tue/Wed entry rules.
- Timeframe is a parameter (1h/4h/1d) — don't hardcode "daily".
- Determinism: seed nothing random; same inputs → same metrics (judges re-run you).
- Keep `verdict/core/` import-clean: no network at import time; `load_ohlcv` is the only I/O.
