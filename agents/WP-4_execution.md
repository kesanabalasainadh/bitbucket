# WP-4 — Execution / Custody (Track 1)

**You own:** `verdict/execution/` · **Branch:** `wp-4-execution` · **Track 1 stretch.**
**Goal:** turn a `Decision` into a `Fill` — first in paper, then via **Trust Wallet Agent Kit (TWAK)**
self-custody signing executing a **PancakeSwap** swap on **BSC**. Ship `PaperExecutor` FIRST so WP-5
can run end-to-end immediately.

## Read first
`docs/API_REFERENCE.md` §2 (TWAK), §3 (BSC + BNB SDK), §4 (PancakeSwap); `CONTRACTS.md` (Executor
protocol, `Decision`/`Fill`); `verdict/schema.py`; `docs/HACKATHON_BRIEF.md` §3 (Track-1 rules: token
allowlist, simulated costs, agent wallet address requirement) + §5 (TWAK "best use" rubric).

## Tasks
1. **`verdict/execution/base.py`** — `Executor` protocol (`quote`, `execute`, `balances`) per CONTRACTS.
2. **`verdict/execution/paper.py`** — `PaperExecutor`: simulate fills using current price + the WP-1
   `CostModel` (fee + slippage). Returns `Fill(status="simulated")`. **Deliver this within hour 1.**
3. **`verdict/execution/twak.py`** — `TWAKExecutor`: drive TWAK in **Autonomous Agent Wallet** mode with
   preset rules/limits. Prefer the TWAK **MCP tools**; fall back to the CLI (`twak swap ...`). Install via
   `curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash`; creds from `portal.trustwallet.com`
   into `.env` (`TWAK_ACCESS_ID`, `TWAK_HMAC_SECRET`). TWAK is the **sole signer** (don't hold raw keys
   in app code) — this depth targets the $2k "Best Use of TWAK" prize.
4. **`verdict/execution/pancake.py`** — `PancakeExecutor`: direct `web3.py` path to the PancakeSwap Smart
   Router as a fallback/comparison. Handle ERC-20 `approve` before first swap; resolve the router address
   from live docs at runtime (don't hardcode). Respect the BEP-20 token allowlist.
5. **Testnet first** — BSC testnet (chainId 97), faucet BNB. Prove one real swap → real `tx_hash`.
   Only flip to mainnet (56) when WP-5's risk governor is wired and limits are tiny.
6. **(Optional) ERC-8004 identity** — register the agent via the BNB AI Agent SDK to (a) mint the **agent
   wallet address** the BUIDL form needs and (b) chase the $2k "Best Use of BNB AI Agent SDK" prize.
7. **Tests** — `PaperExecutor` deterministic fills; TWAK/Pancake behind a `--live` flag, mocked otherwise.

## Acceptance
- `PaperExecutor.execute(decision)` returns a valid `Fill` (used by WP-5 immediately).
- Checkpoint-5: one **testnet** PancakeSwap swap returns a `Fill` with a real `tx_hash`.
- Slippage guard: a swap exceeding `RiskLimits.slippage_bps_max` is rejected, not sent.

## Gotchas
- Self-custody = **keys never in the repo or logs**. `.env`/keystore only; `.gitignore` already blocks them.
- Token approvals cost gas and are per-token, one-time — cache approval state.
- Mainnet uses **real funds** — keep position sizes tiny until the governor (WP-5) is enforcing limits.
- The agent wallet address must be **resolvable** for the Track-1 BUIDL submission — surface it to WP-6.
