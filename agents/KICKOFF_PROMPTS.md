# KICKOFF PROMPTS — paste one per Claude Code session (ultracode, in this repo)

> Detailed, self-contained kickoff prompts for each work package. Open a new Claude Code session in
> `~/Desktop/DoraHacks/verdict`, turn on **ultracode**, paste **one** block. Each prompt bakes in the
> shared contracts, the integration points, the acceptance gate, and the git discipline — the agent has
> everything it needs to run autonomously. These supersede the thin stubs in `agents/README.md`.

## Environment is ALREADY provisioned (don't redo this)
- Python 3.12. Installed: `pydantic v2, pandas, numpy, ccxt, ta, matplotlib, pytest, httpx, requests, pyarrow, python-dotenv`.
- `python -c "import verdict.schema"` passes. `.env` exists (copied from `.env.example`, **gitignored** — keys still blank).
- Safety sweep is clean: only `.env.example` is tracked. **CMC key not yet provided** → build the offline paths.

## Launch order
1. **WP-1** + **WP-3** together (foundation, disjoint dirs, no conflict).
2. **WP-2** next (needs WP-1's signatures; can start against a stub, finalize after WP-1 merges).
3. **WP-4** (paper-first) + **WP-6** (continuous).
4. **WP-5** (after WP-3/WP-4 expose interfaces).
If capacity is tight: **WP-1 → WP-2 → WP-6** guarantees a Track-2 submission.

## Git discipline (every prompt enforces it)
Branch `wp-N-<name>`; commit small; `git pull` before merging to `main`; never force-push shared branches;
PUBLIC repo so secrets live only in `.env`. To change a shared type, edit `verdict/schema.py` + `CONTRACTS.md`
in ONE commit and announce it (QA tracks these).

---

## WP-1 — Quant Core  (Track-2 critical path · branch `wp-1-quant-core` · owns `verdict/core/`)

```
Ultracode. You are WP-1 (Quant Core) for VERDICT — an LLM-authored crypto strategy engine
(BNB HACK: AI Trading Agent Edition). The repo root is your cwd. Environment is already provisioned
(python 3.12 with pydantic v2, pandas, numpy, ccxt, ta, matplotlib, pytest; `import verdict.schema` passes).

READ FIRST, in order: CONTRACTS.md, verdict/schema.py, docs/API_REFERENCE.md (§1), agents/WP-1_quant_core.md.
Then READ the engine you are porting from NSE stocks to crypto (reference only, do NOT run as-is):
  reference/legacy_nse/src/backtest/swing_backtester.py   (no-lookahead day loop, ATR sizing, SL/target/max-hold — YOUR TEMPLATE)
  reference/legacy_nse/src/backtest/cost_model.py         (target_clears_costs entry gate — swap NSE charges for DEX fees+slippage)
  reference/legacy_nse/src/indicators/technical.py        (pure EMA/RSI/MACD/ATR/ADX)
  reference/legacy_nse/scripts/run_walkforward.py         (rolling train/test/step, hold-out, buy&hold baseline)
  reference/legacy_nse/src/backtest/regime.py             (context gate — optional; repoint to BTC-trend/funding later)

HARD RULES:
- You OWN verdict/core/ ONLY. Never edit verdict/schema.py, CONTRACTS.md, requirements.txt, or any other dir.
- Import all shared types from verdict.schema; never redefine them.
- Branch wp-1-quant-core. TDD: write tests from the contract first. Commit small. PUBLIC repo — no secrets.
- DETERMINISM IS GRADED: no RNG, no time/network at import. Same inputs -> identical StrategyMetrics. Tests fully offline.
- Crypto is 24/7: drop all NSE holiday/weekday gates. Timeframe (1h/4h/1d) is a parameter, never hardcoded.

IMPLEMENT exactly the CONTRACTS.md WP-1 signatures, all under verdict/core/:
1. data.py  -> load_ohlcv(symbol, timeframe, start, end, source="cmc") -> OHLCVSeries.
   Implement source="ccxt" (Binance public OHLCV via ccxt; symbol "BNB/USDT", timeframe "1h"/"4h"/"1d").
   Leave source="cmc" raising a clear NotImplementedError pointing at WP-3's CMCClient.ohlcv. Optional parquet cache.
   load_ohlcv is the ONLY function that does network I/O.
2. indicators.py -> pure DataFrame functions for every indicator the grammar (below) needs. No side effects.
3. rules.py -> the DETERMINISTIC RULE GRAMMAR below (this is the contract WP-2 codes against). Document supported
   tokens in the module docstring AND export a module-level SUPPORTED dict so WP-2 can match it 1:1.
4. costs.py -> class CostModel: round_trip_cost(notional_usd)->float (PancakeSwap v2 0.25% LP/taker fee +
   configurable slippage bps + optional flat gas usd); clears_costs(expected_profit_usd, notional_usd, k=3.0)->bool.
5. backtest.py -> backtest(series, spec, costs) -> StrategyMetrics (HONOR this exact signature). STRICT no-lookahead:
   evaluate rules on bar t close, FILL AT t+1 OPEN (apply slippage). Long-only is fine for v1. Risk-based sizing from
   spec.position_size + stop distance. Net round-trip costs every trade. Compute return_pct, sharpe_ratio (annualize by
   sqrt of bars-per-year for the timeframe), win_rate, max_drawdown (positive %), num_trades, profit_factor (risk_score=0;
   WP-2 fills the composite). ALSO provide backtest_detailed(series, spec, costs) -> dataclass
   BacktestResult(metrics, equity_curve, benchmark_curve, drawdown_curve, trades) where benchmark_curve is buy&hold of the
   asset over the same bars; backtest() wraps it. Add CLI `python -m verdict.core.backtest --demo` that tries real BNB/USDT
   4h candles via ccxt and, on ANY failure, falls back to a deterministic synthetic series, then prints StrategyMetrics JSON.
6. walkforward.py -> walk_forward(series, spec, costs, train_bars, test_bars, step_bars) -> list[WalkForwardWindow]
   (HONOR signature). Per test window set passed = strategy beat buy&hold net of costs that window. ALSO provide
   walk_forward_detailed(...) -> dataclass (windows, strategy_returns, benchmark_returns) so WP-2's select.py can compute
   median-vs-benchmark and the 60%-of-windows criterion.
7. curves.py -> equity_drawdown(fills_or_returns) -> (equity:list[float], benchmark:list[float], drawdown:list[float]).
8. tests under verdict/core/tests/ (offline, synthetic data only):
   - clean uptrend -> positive net return for a trend strategy;
   - LOOKAHEAD PROBE: shuffling FUTURE bars (after t) must NOT change any decision/fill made through t — assert identical;
   - cost gate rejects a thin-edge trade (profit < k * round_trip_cost);
   - determinism: two runs on identical input -> identical StrategyMetrics;
   - walk_forward returns >=3 windows with boolean passed flags on a long synthetic series.

DETERMINISTIC RULE GRAMMAR (rules.py — the contract WP-2's candidates emit against):
  Precompute strictly-causal columns: close, open, high, low, volume, ema_<N>, sma_<N>, rsi_<N>, atr_<N>, adx_<N>,
    macd, macd_signal, macd_hist (12/26/9), bb_upper, bb_lower, bb_mid (20,2), donchian_high_<N>, donchian_low_<N>, vol_sma_<N>.
    Parse N out of the token so arbitrary windows work.
  Operand = a column, a number, or "<col>*<k>" / "<col>+<k>" / "<col>-<k>". Supported rule forms (case-insensitive):
    "<lhs> > <rhs>" | "< | >= | <="
    "<col> in [<a>,<b>]"                              e.g. "rsi_14 in [40,65]"
    "<a> crosses_above <b>" | "<a> crosses_below <b>" (t-1 vs t)
    "abs(<a>-<b>)/<b> <= <p>"                         e.g. "abs(close-ema_20)/ema_20 <= 0.02"  (within 2%)
    "<col> rising" | "<col> falling"                 (t vs t-1; e.g. "macd_hist rising")
  Semantics: ENTRY fires when ALL entry_rules are true on bar t close (AND); fill t+1 open. EXIT: parse stop_loss/
  take_profit of form "<k> * ATR(<N>)" or "<p>%"; honor "max_hold=<n> bars" in exit_rules; evaluate any grammar exit_rules
  (e.g. "rsi_14 > 70"). On a bar check STOP before TARGET (conservative); first triggered exit wins. Provide
  evaluate_rule(df, t, rule)->bool and rules_all(df, t, rules)->bool.

ACCEPTANCE (Checkpoint 2): `python -m pytest verdict/core -q` green; `python -m verdict.core.backtest --demo` prints a
StrategyMetrics JSON; walk_forward returns >=3 windows with passed flags. Then commit, push wp-1-quant-core, and post the proof.
```

---

## WP-3 — CMC Signals  (Track 2+1 · branch `wp-3-cmc-signals` · owns `verdict/signals/`)

```
Ultracode. You are WP-3 (CMC Signals) for VERDICT (BNB HACK: AI Trading Agent Edition). Repo root is cwd.
Environment is provisioned (python 3.12, pydantic v2, pandas, ccxt, httpx; `import verdict.schema` passes).
There is NO CMC API key yet — your #1 priority is the OFFLINE FIXTURES PATH so WP-1/WP-2 can integrate today.

READ FIRST, in order: CONTRACTS.md (WP-3 signatures), verdict/schema.py (Signal, OHLCVSeries),
docs/API_REFERENCE.md §1 (MCP/REST/x402, the 12 tools, and the TWO different header names), agents/WP-3_cmc_signals.md.

HARD RULES:
- You OWN verdict/signals/ ONLY. Import shared types from verdict.schema; never redefine them.
- NO raw CMC dicts may leak past this module — every method returns typed values / schema objects only.
- Branch wp-3-cmc-signals. TDD, commit small. PUBLIC repo — keys live only in .env. Tests fully offline (no network, no key).

IMPLEMENT exactly the CONTRACTS.md WP-3 signatures, all under verdict/signals/:
1. cmc.py -> class CMCClient: quotes(symbols)->dict[str,float]; technicals(symbol)->dict[str,float]
   (rsi, macd, ema_20/50/100, atr, adx); derivatives()->dict (funding, OI, liquidations);
   global_metrics()->dict (fear_greed, btc_dominance); ohlcv(symbol,timeframe,start,end)->OHLCVSeries.
   Three transports behind one class, chosen by config/env:
     MCP (default): POST https://mcp.coinmarketcap.com/mcp  header X-CMC-MCP-API-KEY (env CMC_MCP_API_KEY)
     REST (fallback): https://pro-api.coinmarketcap.com    header X-CMC_PRO_API_KEY (env CMC_PRO_API_KEY)
     x402 (optional, behind a flag): https://mcp.coinmarketcap.com/x402/mcp — stub/guard only, don't require eth-account.
   httpx with timeouts + retry/backoff. CAREFUL: the two header names differ (easy bug). If a tool id is rejected,
   the live path should be able to call tools/list and match the exact name.
2. normalize.py -> build_signal(symbol, client) -> Signal. Map CMC fields into Signal: price, indicators{rsi, macd,
   macd_signal, ema_20, ema_50, ema_100, atr, adx}, funding_rate, open_interest, fear_greed, btc_dominance, and DERIVE
   regime ("risk_on"/"risk_off"/"neutral") from Fear&Greed + BTC trend; narratives optional. Document the regime logic.
3. ohlcv.py -> implement CMCClient.ohlcv() -> OHLCVSeries (CMC ohlcv/historical or DEX OHLCV). If CMC history is too shallow,
   fall back to ccxt (same shape as WP-1's load_ohlcv) and tag source accordingly ("cmc" vs "ccxt-binance").
4. fixtures/ -> commit realistic cached JSON for quotes/technicals/derivatives/global_metrics/ohlcv for BNB + a couple of
   majors, plus an OFFLINE client mode that reads them so EVERYTHING is unit-testable WITHOUT a key. Ship this first.
5. tests under verdict/signals/tests/ (offline): parse fixtures into VALID Signal/OHLCVSeries (assert pydantic validation);
   assert regime derivation; assert the right header name per transport; assert no method returns an off-contract raw dict.

ACCEPTANCE: `python -m pytest verdict/signals -q` green; `python -m verdict.signals.cmc --symbol BNB/USDT --offline` prints a
valid Signal JSON from fixtures. Then commit, push wp-3-cmc-signals, and tell WP-1/WP-2 the fixtures are available.
```

---

## WP-2 — Strategy Skill + Selection  (THE Track-2 deliverable · branch `wp-2-skill` · owns `skills/verdict-strategy/`, `verdict/core/{candidates,select}.py`)

```
Ultracode. You are WP-2 (Strategy Skill + Selection) for VERDICT — this is the Track-2 DELIVERABLE we submit.
Repo root is cwd. Depends on WP-1's signatures: if verdict/core/{backtest,walkforward,curves,rules}.py exist, code against
them; if not yet merged, stub a backtester with the SAME signatures and swap to the real one when WP-1 lands.

READ FIRST, in order: docs/HACKATHON_BRIEF.md (§6 skill format + the reference winner, §7 our angle),
CONTRACTS.md (the 3-criterion rule + the StrategySpec JSON example), verdict/schema.py, docs/API_REFERENCE.md §1d.
If WP-1 has merged, READ verdict/core/rules.py and its SUPPORTED export — your candidate rule strings MUST use ONLY that grammar.
Reference to BEAT (study, don't copy): github.com/Ryan4N72/BNB-track2 (SignalForge AI). They have NO walk-forward, NO
pre-registered selection, NO cost-aware gate, NO honest null result — those four are exactly our edge; make them loud.
Port the rule library from reference/legacy_nse/src/strategy/{swing_signal_generator,entry_variants}.py.

HARD RULES:
- You OWN skills/verdict-strategy/ + verdict/core/candidates.py + verdict/core/select.py ONLY. Don't touch other verdict/core files.
- Import shared types from verdict.schema. Branch wp-2-skill. TDD, commit small. PUBLIC repo — no secrets.
- DETERMINISM IS GRADED: every final spec number comes from CODE (the backtester), never from an LLM guess.

IMPLEMENT:
1. verdict/core/candidates.py -> generate_candidates(series, signal) -> list[StrategySpec]. Build >=3 deterministic
   archetypes — Momentum/trend-pullback, Mean-reversion (RSI/Bollinger), Breakout (Donchian/volume). Parameterize from the
   signal (tighten in risk_off; use funding-rate sign as a filter). EVERY entry_rules/exit_rules string MUST be expressible
   in WP-1's rules.py grammar so the backtester can evaluate it 1:1.
2. verdict/core/select.py -> select(candidates, series, costs) -> AgentVerdict. For each candidate: run walk_forward (use
   walk_forward_detailed for benchmark series), fill metrics/walkforward/curves, compute risk_score (0-100; document the
   weighted blend of Sharpe, drawdown, win-rate, window consistency in the spec). Apply the PRE-REGISTERED 3-CRITERION RULE
   (CONTRACTS §criteria): (1) median OOS return > buy&hold over the same windows; (2) positive in >=60% of windows;
   (3) sharpe_ratio >= 1.0 AND max_drawdown <= 25%. A candidate is TRADE-eligible only if ALL THREE hold. Pick the highest
   risk_score among passers -> verdict=TRADE; if none pass -> verdict=NO_TRADE with per-candidate rejected reasons. Fill
   criteria + a plain-English summary. Add `__main__` so `python -m verdict.core.select --assets BNB/USDT,ETH/USDT --tf 4h`
   prints AgentVerdict.model_dump_json(indent=2).
3. skills/verdict-strategy/SKILL.md -> Anthropic Agent Skills format. Front-matter: name: verdict-strategy; multi-line
   description containing a `Trigger:` line (/verdict, "build a backtested crypto strategy", "generate a strategy spec");
   license: MIT; compatibility: ">=1.0.0"; user-invocable: true; allowed-tools: ONLY the CMC MCP tool ids you actually call
   (mcp__cmc-mcp__get_crypto_quotes_latest, mcp__cmc-mcp__get_crypto_technical_analysis, mcp__cmc-mcp__get_global_metrics_latest,
   mcp__cmc-mcp__get_global_crypto_derivatives_metrics). Body: Prerequisites (the mcpServers CMC JSON config), Core Principle
   ("generate many, trust only walk-forward survivors, report honestly"), numbered Workflow (each step names the CMC tool +
   fields, then runs `python -m verdict.core.select ...`), output Template (the AgentVerdict JSON), Adaptation (per risk_profile/
   asset), Failure-Handling (partial data -> still emit a spec at lower confidence).
4. skills/verdict-strategy/scripts/run.py -> deterministic entrypoint the SKILL.md calls: WP-3 build_signal (or a cached
   fixture if no key) -> generate_candidates -> select -> JSON + curves PNGs.
5. skills/verdict-strategy/examples/ -> commit a sample AgentVerdict JSON + the 3 curve PNGs from a real BNB/CAKE/BTC/ETH run.

ACCEPTANCE: `python -m verdict.core.select --assets BNB/USDT,ETH/USDT --tf 4h` prints a schema-valid AgentVerdict; SKILL.md
front-matter parses and allowed-tools are real CMC ids; a judge can `cp -r skills/verdict-strategy` into their agent and run
/verdict; the output clearly shows walk-forward windows and why the winner won / others were rejected. Commit, push wp-2-skill.
```

---

## WP-4 — Execution / Custody  (Track 1 stretch · branch `wp-4-execution` · owns `verdict/execution/`)

```
Ultracode. You are WP-4 (Execution/Custody) for VERDICT, Track 1. Repo root is cwd. Ship PaperExecutor FIRST so WP-5
can run end-to-end immediately; the TWAK/PancakeSwap on-chain paths come second and stay behind a --live flag.

READ FIRST, in order: docs/API_REFERENCE.md §2 (TWAK), §3 (BSC + BNB AI Agent SDK), §4 (PancakeSwap); CONTRACTS.md
(Executor protocol + Decision/Fill); verdict/schema.py; docs/HACKATHON_BRIEF.md §3 (Track-1 rules: ~149-token BEP-20
allowlist, simulated costs, drawdown-cap DQ, min-trade-count, agent-wallet-address requirement) + §5 (TWAK "best use" rubric).

HARD RULES:
- You OWN verdict/execution/ ONLY. Import shared types from verdict.schema. Branch wp-4-execution. TDD, commit small.
- Self-custody: PRIVATE KEYS NEVER in repo or logs — .env / keystore only (.gitignore already blocks them). PUBLIC repo.
- On-chain paths gated behind --live; everything mocked/paper by default so CI and teammates run keyless.

IMPLEMENT (CONTRACTS.md WP-4 signatures), all under verdict/execution/:
1. base.py    -> Executor Protocol: quote(decision)->dict, execute(decision)->Fill, balances()->dict[str,float].
2. paper.py   -> PaperExecutor: simulate fills from current price + WP-1's CostModel (fee+slippage); Fill(status="simulated").
                 Deterministic. DELIVER THIS FIRST — it unblocks WP-5.
3. twak.py    -> TWAKExecutor: drive Trust Wallet Agent Kit in Autonomous Agent Wallet mode (preset rules/limits). Prefer the
                 TWAK MCP tools; fall back to CLI (`twak swap ...`). Install: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash;
                 creds (TWAK_ACCESS_ID, TWAK_HMAC_SECRET) from portal.trustwallet.com into .env. TWAK is the SOLE signer.
4. pancake.py -> PancakeExecutor: direct web3.py path to the PancakeSwap Smart Router as fallback/comparison. Handle ERC-20
                 approve before first swap; RESOLVE the router address from live docs at runtime (don't hardcode). Respect allowlist.
5. Testnet first (BSC chainId 97, faucet BNB): prove one real swap -> real tx_hash. Mainnet (56) only after WP-5's governor
   is wired and limits are tiny. Slippage guard: reject any swap exceeding RiskLimits.slippage_bps_max (don't send it).
6. (Optional) ERC-8004 identity via the BNB AI Agent SDK to mint the agent wallet address the BUIDL form needs ($2k special prize).
7. tests: PaperExecutor deterministic fills; TWAK/Pancake behind --live, mocked otherwise.

ACCEPTANCE: PaperExecutor.execute(decision) returns a valid Fill (WP-5 uses it immediately); a testnet PancakeSwap swap returns
a Fill with a real tx_hash; over-slippage swap is rejected. Surface the agent wallet address to WP-6. Commit, push wp-4-execution.
```

---

## WP-5 — Runtime Agent + Risk Governor  (Track 1 stretch · branch `wp-5-runtime` · owns `verdict/agent/`)

```
Ultracode. You are WP-5 (Runtime + Risk Governor) for VERDICT, Track 1. Repo root is cwd. Build the live loop that ties it
together and SURVIVES the Jun 22-28 held-out window without breaching the drawdown cap. Run end-to-end against PaperExecutor first.

READ FIRST, in order: docs/HACKATHON_BRIEF.md §3 (Track-1 risk gates: drawdown-cap DQ ~30% so set ours lower; min-trade-count
~1/day; simulated costs) + §5 (judged on returns + drawdown + risk-adjusted + rule adherence); CONTRACTS.md (WP-5 signatures +
RiskLimits); verdict/schema.py. READ the proven loop you are porting:
  reference/legacy_nse/src/trading/swing_engine.py  (decision loop, order retry, fill verification, position persistence,
                                                     reconciliation, kill-switch, paper/live gating — strip Upstox, keep control flow + safety)
  reference/legacy_nse/src/safety/risk_guards.py    (daily-loss kill-switch + cooldown)

HARD RULES:
- You OWN verdict/agent/ ONLY. Import shared types from verdict.schema. Branch wp-5-runtime. TDD, commit small. PUBLIC repo.
- Enforce risk limits HARD. Idempotency: never double-send on retry. Checkpoint state to disk atomically (port the JSON-state pattern).

IMPLEMENT (CONTRACTS.md WP-5 signatures), all under verdict/agent/:
1. governor.py -> RiskGovernor.check(decision, state) -> (ok, reason) enforcing RiskLimits: HARD max-drawdown kill-switch
   (flatten + halt past the cap), daily-loss limit, max-position %, max-open-positions, slippage cap, token allowlist, and the
   min-trades-per-day rule (so we aren't DQ'd for inactivity).
2. strategy.py -> adapt the selected StrategySpec (from WP-2's AgentVerdict) into a live decide(signal) -> Decision; size from
   position_size + RiskLimits.
3. loop.py     -> run(strategy, signals, executor, limits, mode): scheduled poll (cadence from timeframe) -> build signal (WP-3)
   -> decide -> governor.check -> execute (WP-4) -> record Fill -> update equity/PnL -> structured logs. Modes paper->testnet->
   mainnet (env VERDICT_MODE); --confirm-live required for mainnet.
4. pnl.py      -> equity curve, realized/unrealized PnL, drawdown tracking (drives the kill-switch and WP-6's post-run report).
5. tests: drive the loop with PaperExecutor + fixture signals over a canned price path; assert the governor HALTS on a drawdown
   breach and BLOCKS an over-limit position; assert allowlist enforced.

ACCEPTANCE: `python -m verdict.agent.loop --mode paper` runs a full session on fixtures and prints a PnL report; governor unit
tests prove drawdown-breach -> flatten+halt and over-cap size -> rejected. Commit, push wp-5-runtime.
```

---

## WP-6 — Submission / Brand / Demo  (both tracks · branch `wp-6-submission` · owns `submission/`, root `README.md`, `reports/`)

```
Ultracode. You are WP-6 (Submission/Brand) for VERDICT. Repo root is cwd. You write NO core code — you make the work legible
and persuasive and run the gates that get us across the line. Hard lock: Jun 21 12:00 UTC; leave a >=4h buffer.

READ FIRST, in order: docs/HACKATHON_BRIEF.md §4 (deliverables: PUBLIC repo MANDATORY; demo video optional; reproducibility
REQUIRED), §5 (the 4 Track-2 judging criteria), §7 (our angle); ORCHESTRATION.md (timeline + push runbook); CONTRACTS.md (reuse
the data-flow diagram).

HARD RULES:
- You OWN submission/, root README.md, reports/ ONLY. Branch wp-6-submission. Commit small. PUBLIC repo.
- No token-launch / fundraising language anywhere (explicit hackathon rule). Keep every claim honest and evidence-backed.

PRODUCE:
1. Root README.md (judge-facing) — what VERDICT is, the problem, the architecture (CMC signal -> walk-forward-validated
   strategy engine -> honest verdict -> optional TWAK/BSC execution), a quickstart that reproduces the StrategySpec in ONE
   command, and which sponsor stacks are used. Lead with the moat: rigorous, honest, walk-forward strategy generation.
2. submission/BUIDL.md — DoraHacks submission body: tagline, problem, what we built, tracks entered (Track 2 primary; Track 1
   if it reached testnet), sponsor usage, what's next. Include the public repo URL, demo link, and (Track 1) the agent wallet address.
3. submission/ARCHITECTURE.md + diagram (ASCII + rendered PNG/SVG) of the data flow + the 3-layer sponsor stack (CMC / Trust Wallet / BNB Chain).
4. submission/DEMO_SCRIPT.md — a 2-3 min walkthrough: run /verdict, show candidate generation, the walk-forward windows, the
   honest verdict, the equity/drawdown curves; (Track 1) show a testnet swap. Record it (optional but lifts the demo score).
5. Logo from submission/BRAND.md (VERDICT; BNB-gold + charcoal + teal); assets in submission/assets/.
6. submission/BEST_USE_CMC.md (deep CMC tool usage — our strongest special-prize shot, $2k); if Track 1 lands, BEST_USE_TWAK.md + BEST_USE_BNB_SDK.md.
7. Reproducibility gate: in a CLEAN clone, `pip install -r requirements.txt` then the ONE documented command reproduces the
   StrategySpec JSON + curves. Fix doc drift until it does (hard judging requirement).
8. Pre-submission safety sweep: `git ls-files | grep -iE '\.env|secret|key|hmac|private'` returns ONLY .env.example.

ACCEPTANCE: fresh clone reproduces the Track-2 deliverable from the README in one command; BUIDL.md is paste-ready; logo +
architecture diagram + demo done; safety sweep clean. Commit, push wp-6-submission.
```
