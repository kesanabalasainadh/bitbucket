# HACKATHON BRIEF — BNB HACK: AI Trading Agent Edition

> **Ground-truth facts for every VERDICT agent. Read this first. Do not re-research what is here.**
> Compiled 2026-06-19 from the official CMC hackathon page, the DoraHacks `/detail` JSON payload,
> the reference-winning Track-2 BUIDL, and partner press. Sources at the bottom.

---

## 1. What it is

**BNB HACK: AI Trading Agent Edition** — a 3-week, **$36,000** hackathon co-run by **BNB Chain +
CoinMarketCap (CMC) + Trust Wallet**, hosted on **DoraHacks** (slug `bnbhack-twt-cmc`).

**Theme:** *"Build the Autonomous Trading Agent Stack."* Agents read crypto markets via the **CMC
Agent Hub**, decide, and (Track 1) execute on-chain via the **Trust Wallet Agent Kit (TWAK)** on
**BNB Smart Chain (BSC)**.

**Submit / register:** https://dorahacks.io/hackathon/bnbhack-twt-cmc/

---

## 2. Timeline (UTC) — ⏰ WE ARE AT ~36–48h LEFT

| Date (2026) | Event |
|---|---|
| Jun 3, 12:00 | Registration opens |
| Jun 3–21 | Build phase |
| **Jun 21, 12:00 UTC** | **🔴 SUBMISSION LOCK (hard deadline for BOTH tracks)** |
| Jun 22–28 | Track 1 live trading window (agents trade live on BSC; real PnL tracked) |
| Jun 29 – Jul 5 | Judging / PnL replay + panel review |
| Week of Jul 6 | Winners announced |

From **2026-06-19 12:00 UTC** the lock is **exactly 48h**; from end of today ~**36h**.
**Track 2 is fully completable inside this window. Track 1 must also be *built* by Jun 21**, then it
runs live Jun 22–28.

---

## 3. Tracks

### Track 1 — Autonomous Trading Agents (flagship, ~$24k)
Build a **live agent** that reads CMC signals, decides, and **signs + executes its own
transactions via TWAK** on BSC within user-defined rules. Trades live on PancakeSwap and/or BSC
perps during Jun 22–28.
- **Prizes:** 1st **$10,000** · 2nd **$6,000** · 3rd **$4,000** · 4th **$2,000** · 5th **$2,000**
- **Judged QUANTITATIVELY on live PnL** against a held-out window. Not the 4 discretionary criteria.
- **Risk gates (DQ if violated):** max **drawdown cap (example: 30%)** → blow past it = disqualified
  regardless of return; a **minimum trade count** (≈ ≥1 trade/day, 7/week) and **simulated tx costs**
  apply. Mantra: *"most profit without blowing up."*
- **Token universe:** a **BEP-20 allowlist (~149 tokens)** — trade only allowlisted assets.
- **Requires** a resolvable **agent wallet address** submitted in the BUIDL form.

### Track 2 — Strategy Skills (lower bar, ~$6k) ← **VERDICT's PRIMARY TARGET**
Build a **CMC Skill** that turns market data into a trading strategy (Quantopian-style quant
research, adapted to crypto, **authored as an LLM Skill**). Deliverable is a **backtestable strategy
spec — NOT a live agent**. No wallet, no chain, no execution.
- **Prizes:** 1st **$3,000** · 2nd **$2,000** · 3rd **$1,000**
- **Judged by a discretionary panel** on 4 criteria (see §5).
- **Deadline = Jun 21 lock.** The Jun 22–28 live window does **NOT** apply to Track 2.

### Special prizes ($6k, stackable with a main placement)
- **Best Use of CoinMarketCap Data & Signal** — **$2,000** ← **very winnable for us**
- **Best Use of Trust Wallet Agent Kit** — **$2,000** (Track 1 only)
- **Best Use of BNB AI Agent SDK** — **$2,000** (Track 1 only)

> **Stacking bonus (both tracks):** must use ≥1 sponsor capability; projects stacking **all three**
> (CMC signal + TWAK execution + BNB venue) **score highest with judges.**

---

## 4. Submission deliverables (verified)

DoraHacks **BUIDL** at the hackathon URL. Confirmed flags from the `/detail` payload:
- **PUBLIC git repo — MANDATORY** (`mandatoryGitRepoLink: true`). GitHub/GitLab/**Bitbucket** ok.
  → **Our repo: `https://github.com/kesanabalasainadh/bitbucket.git`**
- **Demo video — NOT mandatory** (`mandatoryVideoLink: false`). Rule is: *public repo **plus** a demo
  link or video, **OR** clear setup instructions.* (Reference winner submitted repo + writeup, no video.)
- **Reproducibility is required**: a judge must be able to run it from the repo.
- BUIDL custom questions: a **Telegram/email contact** (required) and **agent wallet address**
  (Track 1 only).
- **Rules:** must use ≥1 sponsor capability; **NO token launches** during the event; **AI / vibe-coding
  explicitly encouraged** ("they care that it works, not how it was written").
- **Not required:** pitch deck, long-form docs file, or (Track 2) a contract address.

---

## 5. Judging

- **Track 1:** quantitative — total return over the held-out window, gated by drawdown cap, min trade
  count, and simulated costs. *"Returns, drawdown, risk-adjusted performance, and rule adherence."*
- **Track 2 + all special prizes:** discretionary panel, **4 equally-listed criteria**:
  1. **Technical execution** — does it actually work; is it real, not cosmetic
  2. **Originality** — a new take on a real problem
  3. **Real-world relevance / value** — clear user + plausible adoption path
  4. **Demo & presentation quality**
- No published numeric per-criterion weighting for Track 2 (the 30/25/20/10/10/5 rubric that exists is
  only for the Track-1 "Best Use of TWAK" special prize).

---

## 6. The Track-2 "Strategy Skill" spec (how the deliverable is actually shaped)

> There is **no official JSON schema**. The shape below is the **reference-winner (SignalForge AI)**
> convention the panel accepted, plus the organizer's prose. Treat as best-supported convention.

A CMC **Skill** = a folder `skills/<name>/SKILL.md` in the **Anthropic Agent Skills** format
(front-matter + markdown body; optional `scripts/`, `references/`, `assets/`). It is an instruction
document an agent loads — **not** a compiled plugin. **CMC does not host/run skills**; the SKILL.md
runs locally inside a host agent (Claude Code, Cursor, etc.) that calls CMC data over MCP/x402/REST.
**"Publish to the marketplace" = put SKILL.md in a public repo** (optionally PR the official repo).
There is **no marketplace upload API**, and `find_skill`/`list_skills` are **not** CMC tools.

**SKILL.md front-matter** (verbatim shape from official `market-report` skill):
```yaml
---
name: verdict-strategy
description: |
  Use when a user wants a backtested crypto trading strategy with an honest verdict...
  Trigger: /verdict, "build me a backtested BNB strategy", "generate a crypto strategy spec"
license: MIT
compatibility: ">=1.0.0"
user-invocable: true
allowed-tools:
  - mcp__cmc-mcp__get_crypto_quotes_latest
  - mcp__cmc-mcp__get_crypto_technical_analysis
  - mcp__cmc-mcp__get_global_metrics_latest
  - mcp__cmc-mcp__get_global_crypto_derivatives_metrics
---
```
Body sections: **Prerequisites** (incl. the `mcpServers` JSON config block), **Core Principle**,
numbered **Workflow** (each step names which CMC tool to call + which fields to extract), an output
**Template**, **Adaptation** rules, and per-tool **Failure-Handling** ("deliver a partial result").

**The backtestable StrategySpec** (the JSON the skill emits — see `../CONTRACTS.md` for the exact
schema we standardize on):
- `asset`, `risk_profile`, `horizon`, `lookback`/OHLCV window, `indicators`
- `entry_rules: list[str]`, `exit_rules: list[str]`, `stop_loss`, `take_profit`, `position_size`,
  `risk_limits`
- `metrics: { return_pct, sharpe_ratio, win_rate, max_drawdown, risk_score }`
- `equity_curve`, `benchmark_curve`, `drawdown_curve`
- AI `reasoning` summary, `confidence`, `market_regime`
- Must be **deterministic, inspectable, comparable, backtestable, and exportable as JSON.**

**Reference winner to study (do NOT copy — out-rigor it):**
- BUIDL: https://dorahacks.io/buidl/44900 (SignalForge AI) · Repo: https://github.com/Ryan4N72/BNB-track2
- They generated 3 candidates (momentum / mean-reversion / breakout), backtested with pandas+`ta`,
  picked best risk-adjusted, emitted Pydantic `StrategySkill`+`StrategyMetrics` JSON. **No
  walk-forward, no pre-registered selection, no cost-aware gate — that is exactly our edge.**

---

## 7. Our angle (why VERDICT wins)

Most Track-2 entries are "LLM writes one strategy, backtests once, ships it." **VERDICT ships the
rigor your existing engine already encodes**: generate **N candidate crypto strategies** → **rolling
walk-forward with strict hold-out** → **realistic DEX cost model** → **pre-registered 3-criterion
selection** → emit an honest **AgentVerdict** (the winning spec, *or* "no edge — do not trade").
That maps 1:1 onto **Technical execution + Originality + Real-world relevance**, and the deep CMC tool
usage targets the **$2k Best-Use-of-CMC** special prize. (Track 1 is a stretch built on the same brain.)

---

## 8. Sources
- https://coinmarketcap.com/api/hackathon/
- https://dorahacks.io/hackathon/bnbhack-twt-cmc/ (and `/detail` JSON payload)
- https://dorahacks.io/buidl/44900 · https://github.com/Ryan4N72/BNB-track2
- https://github.com/coinmarketcap-official/skills-for-ai-agents-by-CoinMarketCap
- https://pro.coinmarketcap.com/api/documentation/ai-agent-hub/ (mcp / x402 / skills/overview)
- https://chainwire.org/2026/06/03/bnb-chain-launches-36000-hackathon-to-advance-on-chain-ai-trading-agents/
- https://cryptobriefing.com/bnb-chain-coinmarketcap-and-trust-wallet-launch-36000-bnb-hack-ai-trading-agent-edition/

---

## 9. Track-1 live-competition mechanics (authoritative — from the official page)

> These resolve the items earlier recon flagged as OPEN. Track 2 has **no** on-chain registration.

**On-chain registration (Track 1):** registration is a BSC smart contract that records each agent's
wallet address as an immutable participant list; **entries after the trading window opens are rejected.**
Register via **CLI `twak compete register`** or **MCP action `competition_register`** (both resolve your
agent wallet + submit the tx). **Competition contract:** `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`
(bsctrace.com). Then **also** register + submit the agent address on DoraHacks and explain the strategy.

**Eligible tokens:** a fixed **149-token BEP-20 allowlist** — trades outside it **do not count**
(resolve the authoritative on-chain list at registration). Includes ETH, USDT, USDC, XRP, ADA, LINK,
DOT, UNI, AAVE, ATOM, FIL, INJ, **CAKE, TWT** (BNB-ecosystem assets favored), DOGE, SHIB, AVAX, LTC,
PENDLE, COMP, SUSHI, YFI, SNX, 1INCH, APE, FLOKI, BONK, … (full list in the builder prompt / on-chain).

**Live-competition rules:**
- **Min trades:** ≥1 trade/day (7 over the week) or you don't qualify.
- **Must hold non-zero in-scope assets at start** to be ranked.
- **Dust rule:** returns measured hour-by-hour; any hour that **begins** with portfolio ≤ **$1** scores
  **0% for that hour** — keep capital deployed the whole window.
- **Drawdown DQ:** blow past the max-drawdown cap (e.g. 30%) → disqualified regardless of return.
- Simulated transaction costs apply.

**"Best Use of TWAK" rubric (100 pts, for the $2k special):** TWAK integration depth 30 (sole execution
layer + >1 surface) · self-custody integrity 25 (penalty ladder: full self-custody 20–25; partial
custody 8–15; core loop custodial 0–7) · autonomous execution + guardrails 20 · native x402 usage 10 ·
originality/relevance 10 · demo 5 (show the self-custody signing loop end-to-end + a BSC tx hash).
Tie-break: cleanest self-custody → deepest least-replaceable TWAK → most x402.

**Source:** official DoraHacks/CMC hackathon page (pasted verbatim by the team, 2026-06-19).
