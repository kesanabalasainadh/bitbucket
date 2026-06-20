# ORCHESTRATION — how the parallel agents build VERDICT in ~36–48h

> You (the human) run several Claude Code sessions, each in this repo, each in **ultracode**, same
> model. This file is the conductor's score: what each agent owns, the order, where they sync, and how
> we land the DoraHacks submission. The detailed brief for each agent is in `agents/WP-*.md`.

---

## 0. The one-paragraph plan

We build **VERDICT** — an LLM-authored crypto strategy engine that generates multiple candidate
strategies, validates them with **walk-forward + realistic DEX costs + pre-registered selection
criteria**, and emits an honest **AgentVerdict** (the best risk-adjusted `StrategySpec`, or "no edge").
**Track 2 (Strategy Skill) is the primary, must-win deliverable** — fully completable before the Jun 21
lock and built straight from the migrated engine. **Track 1 (live autonomous agent on BSC via TWAK +
PancakeSwap) is the stretch**, reusing the same brain + the legacy agent-loop scaffolding, and unlocks
the $24k pool plus the TWAK/BNB-SDK special prizes. Every layer leans on CMC, so we also chase the
**$2k Best-Use-of-CMC** prize. See `docs/HACKATHON_BRIEF.md` §7.

---

## 1. Work packages & ownership (each = one parallel session)

| WP | Owner agent | Dir it OWNS (no one else writes here) | Track | Blocking? |
|----|-------------|----------------------------------------|-------|-----------|
| **WP-1** | Quant Core | `verdict/core/` | 2 (critical path) | **Blocks WP-2** |
| **WP-2** | Skill + Selection | `skills/verdict-strategy/`, `verdict/core/select.py`,`candidates.py` | 2 (deliverable) | needs WP-1 contracts |
| **WP-3** | CMC Signals | `verdict/signals/` | 2+1 | independent |
| **WP-4** | Execution/Custody | `verdict/execution/` | 1 | independent (paper first) |
| **WP-5** | Runtime + Risk | `verdict/agent/` | 1 | integrates WP-3/4 (mock first) |
| **WP-6** | Submission/Brand | `submission/`, root `README.md`, `reports/` | both | continuous |

**Conflict rule:** an agent writes ONLY inside its owned dir + the files listed. Shared types live in
`verdict/schema.py` — to change them, edit `schema.py` + `CONTRACTS.md` in one commit and announce.
Each agent works on its **own git branch** `wp-N-<name>`; integration happens via PR/merge into `main`.

**Two lanes (shared repo, ~2x throughput):** the **build lane** (these WP agents) implements features;
a **human teammate runs the QA lane** — testing, finding bugs, fixing them on the other end. Don't
duplicate the QA lane: if you hit a bug outside your WP, flag it instead of racing to fix the same file.
`main` is concurrent — pull before merge, merge cleanly, never force-push shared branches. When you
change a shared contract, announce it so the QA tests track it. (Full rules in `CLAUDE.md`.)

---

## 2. Dependency graph & critical path

```
                 ┌────────────► WP-3 CMC signals ─┐         (independent, start immediately)
 schema.py +     │                                 ├──► WP-5 runtime ──► WP-4 execution ─► TRACK 1 live
 CONTRACTS  ─────┤                                 │            (Track 1 stretch)
 (already done)  │                                 │
                 └──► WP-1 quant core ──► WP-2 skill+select ──► AgentVerdict JSON ─► TRACK 2 SUBMISSION ★
                                                          │
                                              WP-6 submission packages it all
```

- **Critical path to a guaranteed submission:** `WP-1 → WP-2 → WP-6`. Protect it. If time runs out,
  Track 2 + the CMC special prize still ship.
- **WP-3** feeds both tracks; start it in parallel — WP-1 can use CCXT candles until WP-3's CMC OHLCV lands.
- **WP-4/WP-5** are Track-1 stretch; they must reach at least **testnet** by Jun 21 to register a live agent.

---

## 3. Timeline (build lock = Jun 21 12:00 UTC; ~36–48h from 2026-06-19)

**Phase A — Hour 0–2 (you + me, before fan-out):** ✅ repo + contracts + briefs done. Provision keys:
CMC key (blocks WP-2/3), TWAK creds + testnet BNB (blocks WP-4/5). Launch WP-1 and WP-3 first.

**Phase B — Hour 2–12 (parallel build):**
- WP-1: data adapter (CCXT first) → cost model → backtest (no-lookahead) → walk-forward → curves. ★
- WP-3: CMC MCP client → `build_signal()` → OHLCV via CMC.
- WP-4: `PaperExecutor` (so WP-5 unblocks) → TWAK install + autonomous wallet on testnet.
- WP-2: scaffold candidates + selection against WP-1's signatures using a stub backtester.

**Phase C — Hour 12–24 (integration):**
- WP-2 ⟂ WP-1: real walk-forward over BNB/CAKE/BTC/ETH on 1h/4h → produce first real `AgentVerdict`.
- WP-5 ⟂ WP-3 ⟂ WP-4: live loop runs in paper, then testnet (real PancakeSwap swap on testnet).
- WP-6: draft README + architecture diagram + demo script; logo finalized.

**Phase D — Hour 24–36 (harden + submit):**
- Lock the Track-2 `StrategySpec` JSON + SKILL.md; verify it runs reproducibly from a clean clone.
- If Track-1 testnet agent works: register ERC-8004 identity, get the agent wallet address.
- WP-6: record demo, write BUIDL, **push to `origin` (bitbucket)**, submit on DoraHacks. Leave ≥4h buffer.

**Phase E — Jun 22–28:** only if Track 1 submitted — run the live agent through the trading window.

---

## 4. Integration checkpoints (don't skip)

1. **Contracts smoke test** — every agent: `python -c "import verdict.schema"` must pass before coding.
2. **WP-1 done** = `pytest verdict/core` green + a sample `StrategyMetrics` printed from real candles.
3. **WP-2 done** = `python -m verdict.core.select` prints a valid `AgentVerdict.model_dump_json()`.
4. **Track-2 reproducibility gate** = fresh `git clone` + `pip install -r requirements.txt` + one
   documented command reproduces the StrategySpec. (Judges require this.)
5. **Track-1 testnet gate** = one real swap `Fill` with a testnet `tx_hash`.

---

## 5. Git & submission runbook

```bash
# each agent, in its session:
git checkout -b wp-1-quant-core          # own branch
# ...build, commit small...
git push -u origin wp-1-quant-core        # origin = bitbucket.git (PUBLIC — no secrets, .env is gitignored)

# integrator (you or WP-6) merges to main as packages land:
git checkout main && git merge --no-ff wp-1-quant-core
```
- **First push is outward/public** — confirm `.env` is untracked and `git ls-files | grep -i env`
  shows only `.env.example`. The repo `.gitignore` already blocks secrets/keystores/wallets.
- Final submission = public repo URL `https://github.com/kesanabalasainadh/bitbucket` (resolve the
  exact org/name on first push) + a `submission/BUIDL.md` body + (optional) demo video.

---

## 6. How to launch each agent

Open a new Claude Code session **in this repo** (`~/Desktop/DoraHacks/verdict`), turn on ultracode,
and paste the kickoff prompt from `agents/README.md` for that WP. The prompt points the agent at its
`WP-*.md`, the contracts, and the brief — it has everything to work autonomously and split the load.
