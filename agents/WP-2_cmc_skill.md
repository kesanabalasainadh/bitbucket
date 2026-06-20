# WP-2 — Strategy Skill + Selection (THE Track-2 deliverable)

**You own:** `skills/verdict-strategy/`, `verdict/core/candidates.py`, `verdict/core/select.py`
**Branch:** `wp-2-skill` · **Depends on:** WP-1 signatures (stub the backtester until WP-1 lands).
**Goal:** an Anthropic-format **CMC Skill** that pulls CMC data, generates **multiple candidate crypto
strategies**, runs them through WP-1's walk-forward, applies the **pre-registered 3-criterion rule**,
and emits an honest **`AgentVerdict`** JSON (best risk-adjusted spec — or `NO_TRADE`).

## Why you matter
This is what we submit. It must (1) actually work and reproduce, (2) be original — out-rigor the
reference winner, (3) read as real quant research. Maps to all four Track-2 judging criteria.

## Read first
`docs/HACKATHON_BRIEF.md` §6 (skill format + reference winner) & §7, `docs/API_REFERENCE.md` §1d,
`CONTRACTS.md` (criteria + StrategySpec example), `verdict/schema.py`.

## Reference to study — then beat it
`github.com/Ryan4N72/BNB-track2` (SignalForge AI, BUIDL 44900): 3 candidates, single backtest, Pydantic
`StrategySkill`+`StrategyMetrics`. **They have NO walk-forward, NO pre-registered selection, NO
cost-aware gate, NO honest null result.** Those four are our edge — make them loud in the output.
Also port the rule library from `reference/legacy_nse/src/strategy/{swing_signal_generator,entry_variants}.py`
(EMA pullback, 20-day breakout, trend filter, relative strength).

## Tasks
1. **`verdict/core/candidates.py`** — `generate_candidates(series, signal) -> list[StrategySpec]`.
   Build ≥3 archetypes as deterministic `StrategySpec`s: **Momentum/trend-pullback**, **Mean-reversion**
   (RSI/Bollinger), **Breakout** (Donchian/volume). Parameterize from `signal` (e.g. tighten in risk_off,
   use funding-rate sign as a filter). Each spec's `entry_rules`/`exit_rules` are human-readable strings
   that map 1:1 to code the backtester can evaluate.
2. **`verdict/core/select.py`** — `select(candidates, series, costs) -> AgentVerdict`. For each candidate:
   run `walk_forward(...)`, fill `metrics`/`walkforward`/curves, compute `risk_score`. Apply the
   **3-criterion rule (CONTRACTS §criteria)**. Pick the highest `risk_score` among passers → `TRADE`;
   if none pass → `NO_TRADE` with per-candidate `rejected` reasons. Fill `criteria` + `summary`.
   Add a `__main__` that prints `AgentVerdict.model_dump_json(indent=2)`.
3. **`skills/verdict-strategy/SKILL.md`** — Anthropic format (see API_REFERENCE §1d). Front-matter:
   `name: verdict-strategy`; `description` with a `Trigger:` line (`/verdict`, "build a backtested crypto
   strategy", "generate a strategy spec"); `license: MIT`; `compatibility: ">=1.0.0"`;
   `user-invocable: true`; `allowed-tools` = only the CMC MCP tools used (quotes, technicals,
   global_metrics, derivatives). Body: **Prerequisites** (the `mcpServers` CMC config), **Core Principle**
   ("generate many, trust only walk-forward survivors, report honestly"), numbered **Workflow** (call
   `get_crypto_quotes_latest` → `get_crypto_technical_analysis` → `get_global_metrics_latest` →
   `get_global_crypto_derivatives_metrics`; then run `python -m verdict.core.select ...`), output
   **Template** (the AgentVerdict JSON), **Adaptation** (per risk_profile/asset), **Failure-Handling**
   (partial data → still emit a spec, lower confidence).
4. **`skills/verdict-strategy/scripts/run.py`** — the deterministic entrypoint the SKILL.md calls; wires
   CMC signal (WP-3 `build_signal`, or a cached fixture if no key) → candidates → select → JSON + curves.
5. **Sample output** — commit a `skills/verdict-strategy/examples/` AgentVerdict JSON + the three PNG
   curves for the demo, generated from a real run over BNB/CAKE/BTC/ETH on 1h & 4h.

## Acceptance
- `python -m verdict.core.select --assets BNB/USDT,ETH/USDT --tf 4h` prints a schema-valid `AgentVerdict`.
- `SKILL.md` validates as an Anthropic skill (front-matter parses; `allowed-tools` are real CMC ids).
- A judge can `cp -r skills/verdict-strategy` into their agent and invoke `/verdict` and it runs.
- The output clearly shows walk-forward windows + why the winner won / why others were rejected.

## Gotchas
- **Determinism is graded** — the final spec numbers must come from code, not LLM guesses.
- Don't over-claim. If the engine says `NO_TRADE`, ship that with a sharp explanation — it's credibility.
- Keep `allowed-tools` tight (only tools you call) — judges reward depth of real CMC use, not breadth.
