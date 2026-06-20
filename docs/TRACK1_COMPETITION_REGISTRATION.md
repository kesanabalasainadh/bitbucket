# Track-1 Competition Registration — Runbook & Handoff

**Status (2026-06-20):** registration mechanism fully reverse-engineered and the tooling is
installed + authenticated. **Remaining = create wallet → fund → `register` → verify.** Those steps
are deliberately left for the executing agent/human because they spend real BNB and bind our
competition identity on-chain (irreversible). This doc is self-contained — an agent can finish from here.

> **No secrets in this file.** All credentials live only in the gitignored `.env`. This is a PUBLIC repo.

---

## 1. The competition contract (verified facts)

| Field | Value |
|---|---|
| Contract | **`CompetitionRegistry`** (verified on BscScan) |
| Address | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
| Chain | **BNB Smart Chain mainnet**, chainId **56** |
| Explorer | https://bsctrace.com/address/0x212c61b9b72c95d95bf29cf032f5e5635629aed5 · https://bscscan.com/address/0x212c61b9b72c95d95bf29cf032f5e5635629aed5#code |
| Deployer / owner | `0x02c052e406a8b650e2e262ea0efb6d6d87c2de67` (deployed 2026-06-02 17:58 UTC; opened window 21:15 UTC) |
| `registrationStart` | `1780488000` = **2026-06-03 12:00:00 UTC** |
| `registrationDeadline` | `1782345600` = **2026-06-25 00:00:00 UTC** |
| Registered so far | **84 distinct wallets** as of 2026-06-20 (window OPEN) |

### `register()` semantics (selector `0x1aa3a008`)
```solidity
function register() external {
    require(block.timestamp >= registrationStart,   "registration not open");
    require(block.timestamp <  registrationDeadline, "registration closed");
    require(!isRegistered[msg.sender],               "already registered");
    isRegistered[msg.sender] = true;
    emit Registered(msg.sender);            // event Registered(address indexed participant)
}
```
- **No args, non-payable.** The *caller* (`msg.sender`) is the registered participant — so the
  registered address **must be the wallet that will execute trades** (the competition scores per-address).
- View helpers: `isRegistered(address)`, `registrationStart()`, `registrationDeadline()`, `owner()`.
- Other selectors seen on-chain: `0x60806040` (deployment), `0x386c1866` (one-off owner
  `setRegistration*` call that opened the window).

### Evidence
Reverse-engineered from the contract's 85 external txs (`~/Downloads/0x212c61…_external_txs
(2026-05-22_2026-06-20).csv`) + the verified BscScan source. All 84 `register()` calls: value 0,
~49,132 gas, status success. Selector confirmed via 4byte.directory (`0x1aa3a008` → `register()`).

---

## 2. Chosen path — register via Trust Wallet Agent Kit (TWAK)

TWAK ships a **first-class command for this exact hackathon**, so we don't hand-roll a tx:
```
twak compete    BNB HACK: AI TRADING AGENT EDITION — register and check status (BSC)
  ├─ register   Register your agent wallet for the competition (BSC)
  └─ status     Check whether your agent wallet is registered + the deadline
```
Registering the **TWAK-managed BSC wallet** (vs a throwaway key) keeps the registered address ==
trading address, and qualifies us for the **$2k "Best Use of TWAK"** prize. TWAK is non-custodial
(keys are generated locally, AES-256-GCM encrypted, never exported).

### Already done
- ✅ TWAK CLI **v0.19.1** installed (`~/.nvm/versions/node/v22.21.1/bin/twak`; installer:
  `curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash`).
- ✅ `twak init` **configured** — reads `TWAK_ACCESS_ID` / `TWAK_HMAC_SECRET` from `.env`
  (`{"configured": true, "source": "env"}`). Creds are in the gitignored `.env`.
- ✅ BSC chain key confirmed: `bsc`.
- ❌ Wallet not created · ❌ not funded · ❌ not registered  ← **the remaining steps**

---

## 3. Final steps (the executing agent runs these)

> Run with creds in env. From repo root:
> ```bash
> export PATH="$HOME/.nvm/versions/node/v22.21.1/bin:$PATH"
> export TWAK_ACCESS_ID=$(grep -E '^TWAK_ACCESS_ID=' .env | cut -d= -f2 | tr -d ' ')
> export TWAK_HMAC_SECRET=$(grep -E '^TWAK_HMAC_SECRET=' .env | cut -d= -f2 | tr -d ' ')
> ```

1. **Create the agent wallet** (choose a strong password; back up the seed phrase it prints):
   ```bash
   twak wallet create --password "<STRONG_PW>"          # saved to OS keychain by default
   ```
   Store `<STRONG_PW>` in `.env` as `TWAK_WALLET_PASSWORD=` (gitignored) so later steps/automation
   can run non-interactively.

2. **Get the BSC address to fund + submit:**
   ```bash
   twak wallet address --chain bsc --json
   ```

3. **Fund it with gas** — send **~0.001 BNB** to that address on **BNB Smart Chain (BEP-20)**.
   `register()` costs ~0.0000025 BNB; 0.001 is generous headroom. *No mainnet faucet exists* — buy a
   tiny amount on a CEX and withdraw on BSC, or move from an existing wallet. Verify:
   ```bash
   twak wallet balance --chain bsc
   ```

4. **Register** (sends the `register()` tx — irreversible, spends gas):
   ```bash
   twak compete register --password "<STRONG_PW>" --json
   ```

5. **Verify** (expect registered = true; note the deadline):
   ```bash
   twak compete status --password "<STRONG_PW>" --json
   ```
   Cross-check on-chain: `isRegistered(<address>)` should return true and a `Registered` event should
   appear in the tx receipt.

6. **Surface + reconcile (submission):**
   - Record the **agent wallet address** for the BUIDL form (Track 1 requires a resolvable agent
     wallet address) and hand it to **WP-6**.
   - **Honesty fix:** `submission/BUIDL.md` and `submission/DEMO_SCRIPT.md` currently state VERDICT has
     *"zero execution authority — it explains, it never signs… Track-1 future work, deliberately not in
     this codebase."* If we register + trade, those passages must be updated to reflect the real
     on-chain Track-1 identity, or the submission is internally inconsistent (CLAUDE.md golden rule #6).

---

## 4. Deadlines (mind the gap)
- **On-chain registration closes:** 2026-06-25 00:00 UTC.
- **Our hackathon hard lock:** 2026-06-21 12:00 UTC → **register before this** so the wallet address is
  in the submission. Effective runway from now is the 06-21 lock, not the 06-25 contract deadline.

## 5. Open decisions / risks
- **Identity = the registered wallet.** Confirm the TWAK BSC wallet is the one that will actually
  trade. Do **not** register a disposable address.
- **Rotate TWAK creds** at `portal.trustwallet.com` after the hackathon (they were shared in chat).
- **Don't commit secrets.** `.env` (creds, password) stays gitignored. Commit docs on a branch, not
  straight to `main` (golden rule #1).
- **Bonus:** `twak erc8004` (ERC-8004 Identity Registry) mints an on-chain agent identity that earns
  the separate **$2k "Best Use of BNB AI Agent SDK"** prize — optional, after registration.

## 6. Quick read-only re-check (no wallet needed)
A throwaway ethers script proved the read path works (deadline/owner/isRegistered via
`bsc-dataseed.bnbchain.org`); recreate if needed, or just use `twak compete status`.
