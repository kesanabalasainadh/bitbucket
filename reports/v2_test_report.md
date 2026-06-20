# VERDICT V2 System Test Report
**Date:** 2026-06-20
**Tested at commit:** `c8d819c`

## Executive Summary
The V2 engine upgrade is highly robust and structurally sound. The core claims around determinism, no-lookahead leakage, and lack of execution authority hold up under adversarial testing. The system passed the majority of the testing dimensions. 

However, there are a few minor findings and integration risks to note before the final lock:

- **[LOW] Windows Reproducibility Snag:** The documented canonical command uses `&&` which is not universally supported in older Windows Command Prompts (requires PowerShell or bash).
- **[LOW] Pydantic Validation Strictness in Testing:** Generating mock `StrategySpec` objects for testing boundary conditions requires fully populating the `metrics` field at instantiation, otherwise it fails Pydantic validation. This makes writing future tests slightly more cumbersome.
- **[MEDIUM] Sentiment Reconciliation Risk:** This branch uses an offline lexicon for sentiment. The parallel PR `#5` (V3 sentiment) uses real API integration and a cache. The build agent must ensure that when merging V3, the deterministic bounds and `[0, 1]` weight constraints proven here are strictly preserved.

### Top 3 to fix before lock:
1. Ensure the build agent carefully merges the V3 sentiment (from PR #5) into the V2 decision matrix without breaking the 15% weight cap.
2. Update documentation (e.g. `README.md`) to provide Windows-friendly command alternatives (e.g., separating commands instead of using `&&`).
3. Relax or provide test factories for `StrategySpec` to ease testing matrix boundaries without triggering Pydantic `ValidationError`s.

---

## Findings by Dimension

### A) DETERMINISM & REPRODUCIBILITY
**Status:** PASS 
- **Evidence:** Running the canonical `python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h` multiple times produces byte-identical JSON outputs, with the sole exception of the `created_at` timestamps. 
- **Finding [LOW] - Windows Gotchas:** A documented instruction implies `&&` can be used to chain commands. While valid in bash and PowerShell 7+, Windows `cmd.exe` or older PowerShell environments may fail. 
  - *Expected:* OS-agnostic command chains in documentation.
  - *Suggested Fix:* Separate commands in documentation or use cross-platform runner scripts.

### B) NO-LOOKAHEAD / LEAKAGE
**Status:** PASS
- **Evidence:** Extended the causality probe (`verdict/core/tests/test_qa_lookahead.py`) to the new operands (`ema_slope_N`, `bb_width`, `atr_pct`). The probe confirmed that poisoning future bars (at `t > cut`) results in identical trade execution paths for all bars `t < cut`. 
- **Evidence:** Criterion 3 in `select.py` successfully uses walk-forward out-of-sample window medians/maxes for Sharpe and Drawdown. No in-sample data leaks into the risk gate.

### C) KILL SWITCH
**Status:** PASS
- **Evidence:** Executed boundary tests (`test_qa_kill_switch.py`) on `max_drawdown_pct`. The switch activates exactly at `max_allowed_drawdown_pct` (e.g. 25.0) resulting in a `LOCKED` state and `DISABLE_TRADING`.
- **Evidence:** Verified that a tripped kill switch directly blocks trade approval in `matrix.py` (via `risk_blocked`) and overrides the DCA agent narrative to a zero allocation `NO_TRADE`.

### D) DCA AGENT
**Status:** PASS
- **Evidence:** Analyzed `verdict/agent/dca.py`. The module is entirely stateless and functionally pure. It only accepts the matrix result and produces an `AgentNarrative` Pydantic model with text reasoning and an `allocation_pct`. It does not import any web3 libraries, request execution signatures, or make network calls. Execution authority is provably zero.

### E) DECISION MATRIX
**Status:** PASS (with testing caveat)
- **Evidence:** Matrix scores and boundary thresholds evaluate correctly. Tested adversarially: Sentiment components are bounded `[0, 1]` and weighted to a maximum of 15 points. Thus, even with a perfect sentiment score of 1.0, the matrix cannot flip a candidate lacking a validator `TRADE` approval into a `TRADE` state.
- **Finding [LOW] - Pydantic Strictness:**
  - *Repro:* Instantiating a `StrategySpec` without passing a fully formed `metrics` dict in tests.
  - *Observed:* Pydantic throws a `ValidationError`.
  - *Expected:* Testing utilities should provide a default mock `metrics` object.
  - *Suggested Fix:* Add a fixture or builder in `tests/__init__.py` for `StrategySpec`.

### F) SENTIMENT
**Status:** PASS
- **Evidence:** The current branch uses `verdict/sentiment/score.py`, which is an offline, deterministic lexicon-based approach. The score bounds to `[-1.0, 1.0]`. Its total matrix impact is constrained safely, preventing it from manufacturing fake alpha.

### G) END-TO-END + EDGE CASES
**Status:** PASS
- **Evidence:** `demo.py` successfully runs the complete V2 flow. Output validates perfectly against the JSON schema.
- **Evidence:** The xfailed test `test_meanrev_profits_a_ranging_oscillator` in `test_archetype_sanity.py` honestly documents a known limitation ("single-trigger reversion entries catch false dead-cat bounces mid-decline"). It is not a hidden regression, but a documented gap awaiting confluence redesign.
