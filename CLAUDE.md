# CLAUDE.md — read me first (auto-loaded every session)

**This repo = VERDICT**, our entry for **BNB HACK: AI Trading Agent Edition** (CoinMarketCap × Trust
Wallet × BNB Chain, DoraHacks `bnbhack-twt-cmc`). **Public repo. Hard lock: 2026-06-21 12:00 UTC.**

**What VERDICT is:** an LLM-authored crypto strategy engine — generate many candidate strategies →
validate with rolling **walk-forward + DEX cost model + a pre-registered 3-criterion rule** → emit an
honest **`AgentVerdict`** (best risk-adjusted strategy, or `NO_TRADE`). Track 2 (Strategy Skill) is the
must-win deliverable; Track 1 (autonomous BSC agent via TWAK + PancakeSwap) is the stretch.

## Where to look
- `ORCHESTRATION.md` — the build plan + the 6 parallel work packages.
- `CONTRACTS.md` + `verdict/schema.py` — the shared interfaces. **Single source of truth.**
- `docs/HACKATHON_BRIEF.md` — verified hackathon facts (tracks, prizes, judging, deliverables).
- `docs/API_REFERENCE.md` — CMC / Trust Wallet / BNB / PancakeSwap / x402 specifics.
- `agents/WP-1..6.md` — pick the work package for your session (kickoff prompts in `agents/README.md`).
- `reference/legacy_nse/` — proven engine being ported (reference only; do not run as-is).

## Team model (2 humans + agents on this shared repo)
- **Build lane (feature agents):** implement the work packages.
- **QA lane (teammate):** testing, finding bugs, fixing them. Don't duplicate their work — if you find a
  bug outside your WP, flag it rather than racing them to fix the same file.

## Golden rules
1. **Branch per work package:** `wp-N-<name>`. Never commit straight to `main`; `main` is integration.
   Pull before merge; the teammate is pushing concurrently — merge cleanly, no force-push on shared branches.
2. **Own your dir.** Write only inside the directory your WP owns (see `ORCHESTRATION.md` §1).
3. **Shared types live in `verdict/schema.py`.** To change a contract, edit `schema.py` + `CONTRACTS.md`
   in one commit and announce it (the QA tests track these).
4. **Secrets never committed.** Keys go in `.env` (gitignored). This is a PUBLIC repo — sweep before push.
5. **TDD, small commits.** Write the test from the contract first; commit often so QA tests near-HEAD.
6. **Be honest.** A credible `NO_TRADE` beats a hyped strategy. No token-launch / fundraising language
   (explicit hackathon rule).

## External / private — do not touch or publish
`../AlgoTradingJetson` is a separate PRIVATE repo (NSE/Upstox stock trader). Its engine is already
migrated here. Never push its history into this public repo.
