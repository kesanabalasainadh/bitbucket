"""
verdict.identity.attest — record a VERDICT verdict on-chain as the agent's ERC-8004
metadata, using a SECOND BNB AI Agent SDK surface beyond identity registration.

The registered agent (see verdict.identity.register, agentId in submission/
onchain_identity.json) writes a compact, tamper-evident attestation of an AgentVerdict
it produced: the decision (TRADE / NO_TRADE), a content hash of the canonical verdict
(volatile timestamps scrubbed, so the hash addresses the *decision*, not the clock),
the assets/timeframe, and a UTC timestamp. This is written via `ERC8004Agent.set_metadata`,
producing a verifiable BSC-testnet transaction.

Honesty: this is an on-chain *attestation* (a hash commitment), not a trade and not live
execution. It makes VERDICT's strategy output auditable on-chain and tied to the agent's
identity — two ERC-8004 surfaces (identity + metadata), the "Best Use of BNB AI Agent SDK"
angle, without claiming an autonomous trader we did not build.

    python -m verdict.identity.attest --dry-run     # build + hash, no transaction
    python -m verdict.identity.attest               # write attestation on-chain

The wallet key lives in .env (VERDICT_AGENT_PRIVATE_KEY, gitignored). Public proof is
written to submission/onchain_attestation.json (safe to commit — no key).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from verdict.identity.register import DEFAULT_RPC, load_proof

ROOT = Path(__file__).resolve().parents[2]
ATTEST_PATH = ROOT / "submission" / "onchain_attestation.json"
METADATA_KEY = "verdict.latest"
ASSETS = "BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT"
TF = "4h"

# Fields that vary run-to-run; scrubbed before hashing so the hash addresses the
# decision content, not the wall clock.
_VOLATILE = {"created_at", "generated_at", "ts", "timestamp", "attested_at"}


def _keccak(data: bytes) -> str:
    try:
        from eth_utils import keccak
        return "0x" + keccak(data).hex()
    except Exception:
        import hashlib
        return "0x" + hashlib.sha256(data).hexdigest()


def _scrub(obj: Any) -> Any:
    """Recursively drop volatile timestamp fields so the hash is content-addressable."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _VOLATILE}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def canonical_hash(verdict_json: dict) -> str:
    canonical = json.dumps(_scrub(verdict_json), sort_keys=True, separators=(",", ":"))
    return _keccak(canonical.encode("utf-8"))


def latest_verdict_json() -> dict:
    """Run the documented judge command and return its AgentVerdict JSON."""
    out = subprocess.run(
        [sys.executable, "-m", "verdict.core.select", "--assets", ASSETS, "--tf", TF],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if out.returncode != 0:
        raise RuntimeError(f"verdict.core.select failed: {out.stderr[:300]}")
    return json.loads(out.stdout)


def build_attestation(verdict_json: dict, *, now_iso: str) -> dict:
    return {
        "schema": "verdict-attestation/v1",
        "verdict": verdict_json.get("verdict"),
        "verdict_hash": canonical_hash(verdict_json),
        "assets": ASSETS,
        "timeframe": TF,
        "candidates": len(verdict_json.get("candidates", [])),
        "rule": "pre-registered 3-criterion walk-forward, net of PancakeSwap costs",
        "attested_at": now_iso,
    }


def onchain_value(att: dict) -> str:
    """Compact, gas-bounded string written to ERC-8004 metadata."""
    return f"{att['schema']}|{att['verdict']}|{att['verdict_hash']}|{att['assets']}@{att['timeframe']}|{att['attested_at']}"


def attest(*, rpc: Optional[str] = None, dry_run: bool = False,
           save: bool = True, now_iso: Optional[str] = None) -> dict:
    """Build the attestation and (unless dry_run) write it on-chain via set_metadata."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    now_iso = now_iso or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    att = build_attestation(latest_verdict_json(), now_iso=now_iso)
    value = onchain_value(att)

    if dry_run:
        return {**att, "dry_run": True, "onchain_value": value, "metadata_key": METADATA_KEY}

    proof = load_proof() or {}
    agent_id = proof.get("agent_id")
    if agent_id is None:
        raise RuntimeError("No agent_id — run `python -m verdict.identity.register` first.")

    os.environ["RPC_URL"] = rpc or os.getenv("RPC_URL") or DEFAULT_RPC
    from bnbagent import ERC8004Agent, EVMWalletProvider

    key = os.getenv("VERDICT_AGENT_PRIVATE_KEY")
    if not key:
        raise RuntimeError("VERDICT_AGENT_PRIVATE_KEY missing in .env (the agent owner key).")

    wallet = EVMWalletProvider(password=os.getenv("VERDICT_AGENT_PASSWORD", "verdict"), private_key=key)
    sdk = ERC8004Agent(network="bsc-testnet", wallet_provider=wallet)
    result = sdk.set_metadata(int(agent_id), key=METADATA_KEY, value=value)
    tx = result.get("transactionHash")

    out = {
        **att,
        "sdk": "BNB AI Agent SDK (bnbagent)",
        "standard": "ERC-8004 metadata (set_metadata)",
        "network": "bsc-testnet",
        "chain_id": 97,
        "agent_id": agent_id,
        "wallet": proof.get("wallet"),
        "metadata_key": METADATA_KEY,
        "onchain_value": value,
        "tx_hash": tx,
        "explorer_tx": f"https://testnet.bscscan.com/tx/{tx}",
    }
    if save:
        ATTEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        ATTEST_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Attest a VERDICT verdict on-chain (ERC-8004 metadata).")
    ap.add_argument("--rpc", default=None, help=f"BSC testnet RPC (default {DEFAULT_RPC})")
    ap.add_argument("--dry-run", action="store_true", help="build + hash only; no transaction")
    ap.add_argument("--no-save", action="store_true", help="don't write submission/onchain_attestation.json")
    args = ap.parse_args(argv)
    out = attest(rpc=args.rpc, dry_run=args.dry_run, save=not args.no_save)
    print(json.dumps(out, indent=2))
    if not args.dry_run:
        print(f"\n✓ Verdict attested on-chain — agentId {out.get('agent_id')} · {out.get('explorer_tx')}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
