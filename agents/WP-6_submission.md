# WP-6 — Submission / Brand / Demo

**You own:** `submission/`, root `README.md`, `reports/` · **Branch:** `wp-6-submission` · **Continuous.**
**Goal:** package VERDICT into a winning DoraHacks BUIDL — judge-facing README, architecture diagram,
reproducibility, demo, logo, and the three sponsor "best use" writeups. You write no core code; you make
the work legible and persuasive, and you run the gates that get us across the line.

## Read first
`docs/HACKATHON_BRIEF.md` §4 (deliverables: PUBLIC repo mandatory, demo video optional, reproducibility
required), §5 (4 judging criteria), §7 (our angle); `ORCHESTRATION.md` (timeline + push runbook).

## Tasks
1. **Root `README.md`** (judge-facing) — what VERDICT is, the problem, the architecture (CMC signal →
   walk-forward-validated strategy engine → honest verdict → optional TWAK/BSC execution), a quickstart
   that **reproduces the StrategySpec in one command**, and which sponsor stacks are used. Lead with the
   moat: rigorous, honest, walk-forward strategy generation.
2. **`submission/BUIDL.md`** — the DoraHacks submission body: tagline, problem, what we built, tracks
   entered (Track 2 primary; Track 1 if it reached testnet), sponsor usage, what's next. Include the
   public repo URL, the demo link, and (Track 1) the agent wallet address from WP-4.
3. **`submission/ARCHITECTURE.md` + diagram** — a clean diagram (ASCII + a rendered PNG/SVG) of the data
   flow and the 3-layer sponsor stack (CMC / Trust Wallet / BNB Chain). Reuse the flow in `CONTRACTS.md`.
4. **`submission/DEMO_SCRIPT.md`** — a 2–3 min walkthrough script: run `/verdict`, show candidate
   generation, the walk-forward windows, the honest verdict, the equity/drawdown curves; (if Track 1)
   show a testnet swap. Record it (video is optional but lifts the "demo & presentation" score).
5. **Logo** — generate from the prompt in `submission/BRAND.md` (project name **VERDICT**, BNB-gold +
   charcoal + teal). Drop assets in `submission/assets/`.
6. **Sponsor "best use" writeups** — `submission/BEST_USE_CMC.md` (deep CMC tool usage — our strongest
   special-prize shot, $2k), and if Track 1 lands: `BEST_USE_TWAK.md`, `BEST_USE_BNB_SDK.md`.
7. **Reproducibility gate** — in a clean clone: `pip install -r requirements.txt` then the one documented
   command must reproduce the StrategySpec JSON + curves. Fix doc drift until it does. This is a hard
   judging requirement — own it.
8. **Pre-submission safety sweep** — `git ls-files | grep -iE '\.env|secret|key|hmac|private'` returns
   only `.env.example`. No keys, no keystores, no wallets in history.

## Acceptance
- Fresh clone reproduces the Track-2 deliverable from the README in one command.
- BUIDL.md is complete and paste-ready for the DoraHacks form; repo is public and clean.
- Logo + architecture diagram + demo recorded. Safety sweep clean.

## Gotchas
- Demo video is **not** mandatory but reproducible setup **is** — never ship a repo a judge can't run.
- No token launches / fundraising language anywhere (explicit hackathon rule).
- Keep claims honest and evidence-backed — judges value a credible null result over hype.
- Leave a ≥4h buffer before the **Jun 21 12:00 UTC** lock for the submission itself.
