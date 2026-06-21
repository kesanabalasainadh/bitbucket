# VERDICT — Teammate Handoff & Submission State

> **For:** the QA-lane teammate (and their agent).
> **Last updated:** 2026-06-21, `main` @ `82c2b1e`. **126 tests pass, 2 skipped.**
> **Purpose:** so you can pick up instantly — what shipped, how to read the results, what's left,
> and the answers to the questions a judge (or you) will ask. No secrets or private infra in this file.

---

## 1. TL;DR — where we are

- **Track 2 (Strategy Skill) submission is READY.** Public repo, reproducible offline, two live demos,
  126 green tests, real on-chain artifacts.
- **The deliverable** is the CMC **Strategy Skill** (`skills/verdict-strategy/SKILL.md`) + the engine that
  emits a schema-valid `AgentVerdict` JSON (the "strategy spec").
- **The headline output is `NO_TRADE`** on the real BSC majors — **this is the feature, not a bug** (see §3).
- **The only thing left is filing the BUIDL on DoraHacks** (Bala does this on the platform) before the
  **2026-06-21 12:00 UTC** deadline (shows as 08:00 in EDT on the DoraHacks page).

---

## 2. What shipped this session (since the dashboard first appeared)

Newest first — all on `main`:

| Commit | What |
|---|---|
| `82c2b1e` | README: surface the **BNB AI Agent SDK** (2 on-chain surfaces) in the sponsor stack + "submission ready" status |
| `8e20f52` | Docs feature **`verdict.balasainadh.com`** (live CMC) as the primary demo; GitHub Pages as always-up mirror |
| `3276b80` | **Candlestick chart** ("The data behind the verdict") — real OHLCV the backtest runs on, with a BNB/CAKE/BTC/ETH toggle |
| `7eaee41` | **Live market data flow** — dashboard polls `/api/live-cmc` (real CMC) → falls back to free no-key public feeds on static hosts; price flashes on tick. Plus the **timeframe sweep** (NO_TRADE holds across 1h/4h/1d) and per-candidate **findings** data |
| `7c623ec` | **On-chain verdict attestation** — a *second* ERC-8004 SDK surface (`set_metadata`), real BSC-testnet tx. Special-prize doc fixes |
| `b343e22` | **Real, clickable news sources** in the sentiment section (committed real-news fixture; honest, reproducible) |
| `ce69ad4` | Submission polish — contact, two-sided demo clarity, `risk_score` blend doc |
| `155e129` | First **GitHub Pages** static export of the dashboard |

Everything is pushed. Working tree is clean.

---

## 3. **How to read the results** (read this before you worry the strategy "sucks")

The engine returns **`NO_TRADE`** on BNB/CAKE/BTC/ETH (4h). The per-candidate table shows negative returns
(−8% to −70%). **That is the engine doing its job, not failing.**

- Those are **simple momentum / mean-reversion / breakout** strategies losing to **buy-and-hold** on liquid
  majors — which is true of almost all simple TA on BTC/ETH/BNB. The engine **correctly refuses** to endorse
  a strategy that underperforms holding, *net of PancakeSwap costs*.
- The pre-registered rule (committed in `verdict/core/select.py` **before** any results) requires **all three**:
  (1) median OOS return > buy-&-hold, (2) beat B&H in ≥60% of walk-forward windows, (3) Sharpe ≥ 1.0 **and**
  max drawdown ≤ 25%. None of the 12 candidates clears all three → honest `NO_TRADE`.
- **`passed: true/false` is relative to buy-and-hold, not absolute P&L.** A window where the strategy lost 6%
  but B&H lost 25% is `passed: true` (it added value by avoiding the crash). A window where it made 10% but
  B&H made 135% is `passed: false`. This is why walk-forward scoring is *relative*.
- **It is calibrated, not broken-pessimist.** `python skills/verdict-strategy/scripts/two_sided_demo.py` fires
  a genuine **`TRADE`** on a controlled validated-edge regime (mean-reversion, **100% of windows**, OOS Sharpe
  ~10, maxDD 2.4%). So the engine *can* say TRADE — it just honestly declines where no edge survives.

**Why this wins:** the hackathon explicitly rewards honesty — *"we'd rather ship an honest NO_TRADE than a
hyped strategy that loses live."* An independent reviewer (`reports/glm-5.2_simulation_review*.md`) graded the
**engineering A** and called it *"a credible, original, defensible submission."* **Do NOT loosen the criteria
to force a TRADE** — that trivially produces TRADEs but destroys the credibility moat (the reviewer says this
explicitly). The NO_TRADE *is* the product.

---

## 4. The two live demos

- **Primary — `https://verdict.balasainadh.com`**: the full Flask app, self-hosted, with the **CMC key
  server-side** (never in the repo). Shows **`LIVE · CMC`** with real flowing data. *(Ops/host details are
  with Bala — intentionally not in this public repo.)*
- **Backup — `https://kesanabalasainadh.github.io/bitbucket/`**: static GitHub Pages export. Always up, no
  key, no network. Live ticker falls back to free public feeds (labelled `LIVE`, not CMC). Deploy with
  `bash web/deploy_pages.sh` (exports `web/static/*` → `gh-pages`).

Both serve the identical dashboard: live header ticker, candle chart, two-sided verdict, regime grid,
walk-forward, news sentiment with real sources, sponsor stack, on-chain identity + attestation links.

---

## 5. Where to look (quick map)

| You want… | Look at |
|---|---|
| The Track-2 deliverable (the Skill) | `skills/verdict-strategy/SKILL.md` (+ `examples/`) |
| The selection rule / 3 criteria | `verdict/core/select.py` (thresholds at the top — pre-registered) |
| One verdict's full JSON | run `python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h` |
| Two-sided proof (TRADE + NO_TRADE) | `python skills/verdict-strategy/scripts/two_sided_demo.py` |
| The dashboard backend | `web/server.py` (`/api/verdict`, `/api/live-cmc`), data from `web/build_data.py` |
| The dashboard frontend | `web/static/{index.html,app.js,styles.css}` |
| On-chain identity | `verdict/identity/register.py` → `submission/onchain_identity.json` (agentId 1466) |
| On-chain verdict attestation | `verdict/identity/attest.py` → `submission/onchain_attestation.json` (`set_metadata`) |
| CMC integration | `verdict/signals/cmc.py` + `submission/BEST_USE_CMC.md` |
| The submission write-up | `submission/BUIDL.md` (paste into DoraHacks) |

---

## 6. Special-prize positioning (both open to Track 2)

- **Best Use of Agent Hub (CMC)** — our strongest. CMC Skill on the Agent Hub MCP tools (quotes, technicals,
  global metrics, derivatives); live regime (Fear & Greed → risk-off, BTC-dominance → alt-headwind gate).
- **Best Use of BNB AI Agent SDK** — **two** ERC-8004 surfaces with real testnet txs: identity (`register`)
  + verdict attestation (`attest`/`set_metadata`). Honestly framed as attestation, not execution.
- **Best Use of TWAK** — Track-1 only; we don't build TWAK. **Not a target** (we'd score ~0).

---

## 7. Likely questions (and the answers)

- **"Does it actually do anything if it says NO_TRADE?"** → Yes. See §3 + the two-sided demo. NO_TRADE is a
  *judgement* backed by 12 evidenced rejections; the engine issues TRADE when an edge survives.
- **"Is the on-chain part real?"** → Yes — two verifiable BSC-testnet txs (identity `0x1d4ba443…`,
  attestation `0xa4c26cc6…`). `get_metadata` reads the attestation back identically.
- **"Is the live CMC real or faked?"** → Real on `verdict.balasainadh.com` (server-side key). On Pages it's
  honest public-feed data, labelled `LIVE` (not CMC). We never fake liveness.
- **"Can a judge reproduce it?"** → `pip install -r requirements.txt` then the one `select` command. No key,
  no network, byte-identical except the `created_at` timestamp.
- **"Why not Track 1?"** → No live executor / TWAK signing (honestly out of scope; `verdict/execution/` empty).
- **"Did the news headlines get faked?"** → No — `verdict/sentiment/_fixtures/headlines.json` are real,
  dated, sourced articles with working URLs, committed as an as-of snapshot.

---

## 8. Open items / what's left

1. **File the BUIDL on DoraHacks** (Bala, platform action) — Track 2, repo + demo links, contact, flag the two
   specials. **This is the only blocker to submission.**
2. *(Optional, not required)* a 60–90s screen recording of the live dashboard would lift "Demo & presentation."
3. Lane note: build lane owns `verdict/core` + `skills` + `web`; QA lane owns `verdict/signals`. Coordinate on
   shared `verdict/schema.py` changes (single source of truth).

---

## 9. Reproduce everything (offline, no keys)

```bash
pip install -r requirements.txt
pip install -r web/requirements.txt              # only for the dashboard

python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h   # NO_TRADE
python skills/verdict-strategy/scripts/two_sided_demo.py                              # TRADE + NO_TRADE
python -m pytest verdict -q                                                           # 126 pass
python web/build_data.py && python web/server.py                                      # dashboard on :3003
```
