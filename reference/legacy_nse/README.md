# reference/legacy_nse — proven engine to PORT (not run as-is)

These files are migrated from a production **NSE (Indian stock) swing-trading** system. They are here
as **reference to adapt into `verdict/core/`, `verdict/agent/`** — NOT to import directly. They carry
NSE/Upstox assumptions (₹ costs, India VIX/Nifty regime, NSE holidays, daily-only bars, broker REST).

> ⚠️ Honest note: the original strategy **loses to a fixed deposit after costs** (its own walk-forward
> verdict). We are reusing the **rigor of the engine**, not the (losing) signal. Re-derive the edge on
> crypto data; if none survives walk-forward, VERDICT says `NO_TRADE` — and that honesty is the pitch.

## File map → where it goes

| Reference file | Port into | Keep | Strip / replace |
|---|---|---|---|
| `src/backtest/swing_backtester.py` | `verdict/core/backtest.py` | no-lookahead loop (signal@close, fill@next-open), ATR sizing, SL/target/stale/max-hold, trailing/partial exits | ₹ costs, NSE calendar, daily-only |
| `src/backtest/cost_model.py` | `verdict/core/costs.py` | `target_clears_costs()` gate structure | STT/DP/GST/SEBI → DEX fee + slippage + gas |
| `src/backtest/regime.py` | `verdict/core/` (optional) | tiered context-gate pattern (size/threshold multipliers) | India VIX/Nifty → BTC trend / funding rate |
| `scripts/run_walkforward.py` | `verdict/core/walkforward.py` | rolling train/test/step, hold-out, baselines, md/json/png reporting | "7% FD" baseline → stablecoin/HODL |
| `scripts/diagnose_walkforward.py` | `verdict/core/walkforward.py` | per-window verdict bands, asymmetry thresholds | — |
| `scripts/experiment_*.py` + `experiments/*.md` | `verdict/core/select.py` + methodology | **pre-registered 3-criterion selection discipline** (the moat) | NSE specifics |
| `src/strategy/swing_signal_generator.py` | `verdict/core/candidates.py` (WP-2) | EMA-pullback + MACD + RSI + volume + ADX rule logic | day-of-week gate |
| `src/strategy/entry_variants.py` | `verdict/core/candidates.py` (WP-2) | E0..E4: trend filter, relative strength, breakout — one `generate()` interface | Nifty benchmark → BTC benchmark |
| `src/indicators/technical.py` | `verdict/core/indicators.py` | pure EMA/RSI/MACD/ATR/ADX | nothing (reusable) — or swap to `ta` |
| `src/data/candle_cache.py` | `verdict/core/data.py` | parquet/store shape keyed by symbol+date | Postgres/Upstox loader → ccxt/CMC |
| `src/trading/swing_engine.py` | `verdict/agent/loop.py` (WP-5) | decision loop, order retry, fill verify, reconcile, kill-switch, paper/live gate, `--confirm-live` | Upstox order calls → Executor |
| `src/safety/risk_guards.py` | `verdict/agent/governor.py` (WP-5) | daily-loss kill-switch, cooldowns | NSE/SEBI IP guard |

## Reading the experiments
`experiments/2026-06-11_*_redesign.md` show the **pre-registered hypothesis → committed selection rule →
honest verdict** loop we replicate for crypto. The `*_results.md` show the null outcomes. This
methodology — not the result — is what we're proud of and what judges will respect.
