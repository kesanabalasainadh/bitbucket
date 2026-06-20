# AGENTS — launch instructions for the parallel build

Six work packages, each meant to run as its **own Claude Code session in this repo, in ultracode**.
Open a session, paste the matching kickoff prompt, let it run. Each `WP-*.md` is self-contained.

**Read order for every agent (enforced in each kickoff prompt):**
`docs/HACKATHON_BRIEF.md` → `CONTRACTS.md` → `verdict/schema.py` → `docs/API_REFERENCE.md` → your `WP-*.md`.

**Golden rules (in every WP):**
- Write only inside the dir your WP owns (see `ORCHESTRATION.md` §1). Shared types come from
  `verdict/schema.py` — never redefine them.
- Work on branch `wp-N-<name>`. Commit small. This is a **PUBLIC** repo — secrets go in `.env` (gitignored).
- TDD: write the test from the contract first, then implement. Keep modules small and focused.

---

## Suggested launch order
1. **WP-1** (quant core) + **WP-3** (CMC signals) — start together, they're the foundation.
2. **WP-2** (skill) — start in parallel against WP-1's signatures (stub the backtester until WP-1 lands).
3. **WP-4** (execution, paper-first) + **WP-6** (submission, continuous).
4. **WP-5** (runtime) — once WP-3/WP-4 expose their interfaces.

If you only have capacity for a few sessions: **WP-1 → WP-2 → WP-6** guarantees a Track-2 submission.

---

## Kickoff prompts (copy one per session)

### WP-1 — Quant Core
```
Ultracode. You are WP-1 (Quant Core) for the VERDICT hackathon build.
Read in order: docs/HACKATHON_BRIEF.md, CONTRACTS.md, verdict/schema.py, docs/API_REFERENCE.md,
then agents/WP-1_quant_core.md — and execute it end to end. You own verdict/core/ only.
Port the migrated engine in reference/legacy_nse/ from NSE stocks to crypto. Branch wp-1-quant-core.
TDD, commit small, code strictly to the signatures in CONTRACTS.md. When done, post the checkpoint-2 proof.
```

### WP-2 — Strategy Skill + Selection
```
Ultracode. You are WP-2 (Strategy Skill + Selection) for VERDICT.
Read in order: docs/HACKATHON_BRIEF.md (esp. §6/§7), CONTRACTS.md, verdict/schema.py,
docs/API_REFERENCE.md (§1d), then agents/WP-2_cmc_skill.md — and execute it. You own
skills/verdict-strategy/ and verdict/core/{candidates,select}.py. This is the Track-2 DELIVERABLE.
Out-rigor the reference winner (Ryan4N72/BNB-track2). Branch wp-2-skill. Emit a valid AgentVerdict JSON.
```

### WP-3 — CMC Signals
```
Ultracode. You are WP-3 (CMC Signals) for VERDICT.
Read in order: docs/HACKATHON_BRIEF.md, CONTRACTS.md, verdict/schema.py, docs/API_REFERENCE.md (§1),
then agents/WP-3_cmc_signals.md — and execute it. You own verdict/signals/ only.
One CMCClient over MCP/REST/x402 returning the schema types. Branch wp-3-cmc-signals. Mock-test without a key.
```

### WP-4 — Execution / Custody (Track 1)
```
Ultracode. You are WP-4 (Execution/Custody) for VERDICT, Track 1.
Read in order: docs/HACKATHON_BRIEF.md, CONTRACTS.md, verdict/schema.py, docs/API_REFERENCE.md (§2-4),
then agents/WP-4_execution.md — and execute it. You own verdict/execution/ only.
Ship PaperExecutor FIRST (unblocks WP-5), then TWAK + PancakeSwap on BSC testnet. Branch wp-4-execution.
```

### WP-5 — Runtime Agent + Risk Governor (Track 1)
```
Ultracode. You are WP-5 (Runtime + Risk Governor) for VERDICT, Track 1.
Read in order: docs/HACKATHON_BRIEF.md (esp. §3 Track-1 risk gates), CONTRACTS.md, verdict/schema.py,
then agents/WP-5_runtime_agent.md — and execute it. You own verdict/agent/ only.
Reuse reference/legacy_nse/src/trading/swing_engine.py's loop/retry/reconcile patterns. Branch wp-5-runtime.
Enforce the drawdown/daily-loss/min-trade rules HARD. Run end-to-end against PaperExecutor first.
```

### WP-6 — Submission / Brand / Demo
```
Ultracode. You are WP-6 (Submission/Brand) for VERDICT.
Read in order: docs/HACKATHON_BRIEF.md (esp. §4 deliverables, §5 judging), ORCHESTRATION.md,
then agents/WP-6_submission.md — and execute it. You own submission/, root README.md, reports/.
Produce the BUIDL writeup, judge-facing README, architecture diagram, demo script, logo, and the
sponsor "best use" writeups. Run the reproducibility gate. Branch wp-6-submission.
```

---

## Status board (update as you go)

| WP | Branch | Status | Checkpoint proof |
|----|--------|--------|------------------|
| WP-1 | wp-1-quant-core | ⬜ not started | |
| WP-2 | wp-2-skill | ⬜ not started | |
| WP-3 | wp-3-cmc-signals | ⬜ not started | |
| WP-4 | wp-4-execution | ⬜ not started | |
| WP-5 | wp-5-runtime | ⬜ not started | |
| WP-6 | wp-6-submission | ⬜ not started | |
