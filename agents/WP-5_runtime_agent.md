# WP-5 — Runtime Agent + Risk Governor (Track 1)

**You own:** `verdict/agent/` · **Branch:** `wp-5-runtime` · **Track 1 stretch.**
**Goal:** the live loop that ties it together — poll CMC `Signal` → strategy `Decision` → **risk
governor** → `Executor` → log `Fill` + PnL — and that **survives the Jun 22–28 held-out window without
blowing the drawdown cap**. Reuse the proven loop patterns from the legacy swing engine.

## Read first
`docs/HACKATHON_BRIEF.md` §3 (Track-1 risk gates: drawdown-cap DQ, min-trade-count, simulated costs) +
§5 (judged on returns + drawdown + risk-adjusted + rule adherence); `CONTRACTS.md` (WP-5 signatures +
`RiskLimits`); `verdict/schema.py`.

## Reference to port
`reference/legacy_nse/src/trading/swing_engine.py` — its **decision loop, order retry, fill
verification, position persistence, reconciliation, kill-switch, paper/live gating** are exactly the
autonomous-agent skeleton you need. Strip Upstox specifics; keep the control flow + safety.
`reference/legacy_nse/src/safety/risk_guards.py` — daily-loss kill-switch + cooldown patterns.

## Tasks
1. **`verdict/agent/governor.py`** — `RiskGovernor.check(decision, state) -> (ok, reason)` enforcing
   `RiskLimits`: **hard max-drawdown kill-switch** (flatten + halt if equity draws down past cap — the
   hackathon DQs you at ~30%, so set our cap lower, e.g. 25%), daily-loss limit, max-position %,
   max-open-positions, slippage cap, token allowlist, and the **min-trades-per-day** rule (so we don't
   get DQ'd for inactivity). Persist state atomically (port the legacy JSON-state pattern).
2. **`verdict/agent/strategy.py`** — adapt the selected `StrategySpec` (from WP-2's `AgentVerdict`) into a
   live `decide(signal) -> Decision`. The spec's entry/exit rules drive the decision; size from
   `position_size` + `RiskLimits`.
3. **`verdict/agent/loop.py`** — `run(strategy, signals, executor, limits, mode)`: scheduled poll (cadence
   from timeframe), build signal (WP-3), decide, governor-check, execute (WP-4), record `Fill`, update
   equity/PnL, emit structured logs + optional Telegram (port `telegram_bot.py` if time). Modes:
   `paper → testnet → mainnet` (from `VERDICT_MODE`). `--confirm-live` required for mainnet (port the
   legacy safety gate).
4. **`verdict/agent/pnl.py`** — equity curve, realized/unrealized PnL, drawdown tracking (drives the
   kill-switch and the post-run report WP-6 needs).
5. **Tests** — drive the loop with `PaperExecutor` + fixture signals over a canned price path; assert the
   governor halts on a drawdown breach and blocks an over-limit position.

## Acceptance
- `python -m verdict.agent.loop --mode paper` runs a full session on fixtures and prints a PnL report.
- Governor unit tests prove: drawdown breach → flatten+halt; over-cap size → rejected; allowlist enforced.
- Checkpoint-5 (with WP-4): runs against **testnet**, places a real swap, respects limits.

## Gotchas
- The judge metric is **risk-adjusted return with a drawdown DQ** — "don't blow up" beats "big number".
  Tune conservative; a steady small positive return that never breaches the cap can outscore a volatile
  high-flyer that gets DQ'd.
- Honor **min-trade-count** (≈1/day) — an idle agent can be disqualified.
- Idempotency: never double-send on retry (port the fill-verification/reconcile logic).
- Crypto is 24/7 — the loop must run unattended through the whole window; checkpoint state to disk.
