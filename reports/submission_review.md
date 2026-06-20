# VERDICT Track-2 Submission Review
**Date:** 2026-06-20  
**Reviewed at commit:** 196c548  

## Executive Summary
This is a tough, judge's-eye review of the VERDICT Track-2 submission. The core premise—an honest quant agent that walk-forward validates and outputs NO_TRADE when there's no edge—is incredibly strong and original. However, the documentation currently contains a few critical overclaims and inconsistencies that undermine the "honesty" angle. 

**Top Priorities:**
1. **[BLOCKER]** Fix the data provenance claim. The documentation implies historical candles come from CoinMarketCap, but `verdict/core/data.py` pulls from Kucoin via `ccxt`. 
2. **[HIGH]** Fix the stale test count (`98 passed` vs actual `103 passed`) to maintain credibility.
3. **[HIGH]** Remove claims about consuming `open_interest` and `btc_dominance` unless they are actually wired into candidate logic (currently they are extracted but ignored).

---

## A) HONESTY & ACCURACY AUDIT
**1. Stale Test Count**
*   **Quote:** `BUIDL.md` says "pytest verdict -q -> 98 passed".
*   **Reality:** Running the suite actually yields `103 passed, 3 skipped, 1 xfailed`. In a submission whose entire pitch is rigorous honesty, an outdated metric looks like a fabricated number.
*   **Severity:** `[HIGH]`
*   **Suggested Fix:** Update the docs to say "100+ tests passed" or sync the exact number right before lock.

**2. Candle Provenance (The "CMC" Data)**
*   **Quote:** `data.py` defaults to `source="cmc"` and fixtures are labeled as such. `BEST_USE_CMC.md` leans on deep data integration.
*   **Reality:** `verdict/core/data.py` (`_fetch_ccxt`) actually fetches historical OHLCV from Kucoin via the `ccxt` library, not CoinMarketCap. 
*   **Severity:** `[BLOCKER]` (Major risk for the "Best Use of CMC" prize).
*   **Suggested Fix:** Honestly label the candle provenance as `kucoin` and clarify that CMC is used for the rich signal/regime context layer, not the raw historical OHLCV. 

**3. Unused CMC Fields**
*   **Quote:** `BEST_USE_CMC.md` claims `get_global_crypto_derivatives_metrics` provides "funding rate + open interest -> regime/quality filter".
*   **Reality:** `open_interest` and `btc_dominance` are extracted in `cmc.py` but are *never consumed* by any logic in `candidates.py` or `select.py`. 
*   **Severity:** `[HIGH]`
*   **Suggested Fix:** Either wire these metrics into a concrete rule in `candidates.py` (e.g. `if btc_dominance > 60: ...`), or remove the claim from the writeup.

**4. The "Byte-for-Byte" Claim**
*   **Quote:** `BUIDL.md` claims the CLI reproduces the StrategySpec "byte-for-byte".
*   **Reality:** The output JSON includes a `ts` (timestamp) field that changes on every run. 
*   **Severity:** `[MEDIUM]`
*   **Suggested Fix:** Soften to "structurally identical (excluding the generation timestamp)" or inject a fixed seed timestamp in offline mode.

---

## B) REPRODUCIBILITY
I cloned the repository into a clean Windows directory, initialized a fresh venv, installed `requirements.txt`, and ran the documented `verdict.core.select` command.

*   **Result:** It worked perfectly with no API key and no network, correctly outputting the `NO_TRADE` JSON using the offline fixtures. 
*   **Time-to-first-result:** ~1.5 minutes (primarily bounded by downloading `pandas` and `ccxt` wheels). Execution itself takes ~3 seconds.
*   **Friction / Windows Gotchas:** The README instructs `cd bitbucket && pip install -r requirements.txt`. The `&&` operator is POSIX-native and fails in older Windows PowerShell environments unless wrapped. 
*   **Severity:** `[LOW]`
*   **Suggested Fix:** Split the command into two lines or note that Windows users should run them sequentially. 

---

## C) CMC DEPTH & "Best Use of CMC" Prize
The `BEST_USE_CMC.md` document is compelling, but the integration has weaknesses regarding Basic-tier gating. `cmc.py` successfully degrades to fixtures when technicals/derivatives are gated (403), but a judge testing this with a Basic key will just see silent fallbacks.

**Two concrete strengthening moves:**
1. Log an explicit, visible warning when a CMC endpoint falls back to a fixture due to tier gating, so the judge knows the integration *tried* to use their key.
2. Actually consume the `btc_dominance` and `open_interest` fields in the `market_regime` logic to make the "Depth over Breadth" claim 100% true.

---

## D) DEMO READINESS
Walking through `DEMO_SCRIPT.md` takes about 2.5 minutes and the narrative hits the right beats. 

*   **Does "NO_TRADE" land?** Yes, framing "NO_TRADE" as a feature of an *honest quant* is a massive differentiator. However, the JSON output itself is visually anti-climactic.
*   **What to show:** When the script says "If no strategy clears the hurdle, VERDICT honestly outputs NO_TRADE", the demo *must* cut to the `drawdown_curve.png` or `equity_curve.png` from `examples/`. Visually showing the judge *why* the strategy was rejected (e.g., "Look at this 40% hidden drawdown—this is why we rejected it") is the payoff.

---

## E) JUDGE SIMULATION

*   **Technical Execution: 9/10.** Walk-forward validation and realistic PancakeSwap slippage/fees are real-world quant infrastructure. *Path to 10:* Resolve the `ccxt`/`cmc` provenance gap. 
*   **Originality: 10/10.** An AI agent that actively refuses to trade based on pre-registered rules is a brilliant subversion of the standard hackathon "trading bot" hype.
*   **Real-world Relevance: 9/10.** Deterministic StrategySpecs that port directly to Trust Wallet execution is highly relevant. *Path to 10:* Use dynamic CMC order-book depth for slippage rather than a static 30bps assumption.
*   **Demo & Presentation: 8/10.** The README is exceptional, but a terminal printing `NO_TRADE` is dry. *Path to 10:* Put the equity/drawdown charts front-and-center in the video demo to visualize the agent's reasoning.

---

## Top 3 to fix before lock:
1. **Label the candle data source honestly** (`ccxt`/Kucoin, not CMC) to protect credibility.
2. **Remove or implement `open_interest`/`btc_dominance`** so the CMC best-use writeup is completely factually accurate.
3. **Update the test counts** in the docs to match `main`.
