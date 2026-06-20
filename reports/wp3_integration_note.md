# WP-3 signals — integration note (why `qa/wp3-signals-hardening` was NOT merged)

**Date:** 2026-06-19 · **Author:** build/integrator agent

## What happened
`main` was integrated from `wp-track2-critical-path` (engine + WP-2 deliverable + the full CMC signals
layer: `cmc.py` + `transport.py` + `normalize.py` + `ohlcv.py` + `symbols.py` + 8 fixtures + 5 test
files). `main` is green: `python -m pytest verdict -q` → **98 passed**.

The teammate's branch `qa/wp3-signals-hardening` was **held back** (not merged) because it is not a
hardening of the existing layer — it is a from-scratch *initial* re-implementation that landed on the
wrong base and would **regress** `verdict/signals/`.

## Root cause
The branch was cut from `fdb274a` (early base, **no signals at all**) instead of the shared
`wp-track2-critical-path` snapshot (which already had the signals scaffolding). So `git merge-base
qa wp-track2` = `fdb274a`, and every signals file is an add/add conflict against the fuller version.

## Evidence it's a regression, not hardening
- `technicals()`, `derivatives()`, `global_metrics()` call MCP then **`return {}`** in online mode —
  the response is discarded; real values only come from the hardcoded `offline` branch.
- `ohlcv()` returns **empty bars** online.
- No `transport.py` (no retry/timeout), **no tests**, MCP payload format self-admittedly a guess.
- Non-deterministic `datetime.now()` in `build_signal`.

## Decision
Keep the build side's signals layer (now on `main`). The teammate should re-base their effort onto
`main` and harden the **existing** layer — see `reports/wp3_resume_plan` / the kickoff prompt. Their
`qa/wp3-signals-hardening` branch can be left as-is on origin for reference; do not merge it.
