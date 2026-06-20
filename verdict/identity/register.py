"""
verdict.identity.register — register VERDICT on-chain via the BNB AI Agent SDK.

Uses the BNB AI Agent SDK (`bnbagent`) to mint an ERC-8004 agent identity on BNB
Smart Chain **testnet** — gas-free through the MegaFuel paymaster, so no funds and no
real-trading risk. The result (agentId + tx hash + wallet) is verifiable on
testnet.bscscan.com and is the on-chain proof a Track-2 + "Best Use of BNB AI Agent
SDK" submission can point to.

Honesty: this is an *identity* registration, not live execution. VERDICT is a Track-2
Strategy Skill; the on-chain identity makes the agent discoverable and gives a real
on-chain artifact without claiming an autonomous trader we did not build.

    python -m verdict.identity.register
    python -m verdict.identity.register --rpc https://bsc-testnet-rpc.publicnode.com

The wallet key lives in .env (VERDICT_AGENT_PRIVATE_KEY, gitignored). Public proof is
written to submission/onchain_identity.json (safe to commit — address/agentId/tx only,
never the key).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# The publicnode endpoint is reliable for the gas-sponsored registration flow; the
# SDK's default data-seed RPC can hang on the paymaster step.
DEFAULT_RPC = "https://bsc-testnet-rpc.publicnode.com"
REGISTRY = "0x8004a818bfb912233c491871b3d84c89a494bd9e"   # ERC-8004 identity registry (bsc-testnet)
PROOF_PATH = Path(__file__).resolve().parents[2] / "submission" / "onchain_identity.json"

NAME = "verdict-strategy"
DESCRIPTION = (
    "VERDICT — an honest crypto strategy engine: regime-gated candidate strategies, "
    "rolling walk-forward out-of-sample validation under a PancakeSwap DEX cost model, "
    "a pre-registered 3-criterion rule, and a two-sided TRADE / NO_TRADE verdict."
)
ENDPOINT = "https://github.com/kesanabalasainadh/bitbucket"


def load_proof() -> Optional[dict]:
    """Return the committed on-chain identity proof, if present."""
    if PROOF_PATH.exists():
        return json.loads(PROOF_PATH.read_text(encoding="utf-8"))
    return None


def register(*, rpc: Optional[str] = None, save: bool = True,
             name: str = NAME, description: str = DESCRIPTION,
             endpoint: str = ENDPOINT) -> dict:
    """Register VERDICT as an ERC-8004 agent on bsc-testnet; return the proof dict."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    os.environ["RPC_URL"] = rpc or os.getenv("RPC_URL") or DEFAULT_RPC

    from bnbagent import ERC8004Agent, AgentEndpoint, EVMWalletProvider
    from eth_account import Account

    key = os.getenv("VERDICT_AGENT_PRIVATE_KEY")
    if not key:
        acct = Account.create()
        key = acct.key.hex()
        sys.stderr.write(
            "No VERDICT_AGENT_PRIVATE_KEY in .env — generated a fresh testnet wallet.\n"
            "Add this to .env (gitignored) to reuse the same identity:\n"
            f"  VERDICT_AGENT_PRIVATE_KEY={key}\n")
    address = Account.from_key(key).address

    wallet = EVMWalletProvider(password=os.getenv("VERDICT_AGENT_PASSWORD", "verdict"),
                               private_key=key)
    sdk = ERC8004Agent(network="bsc-testnet", wallet_provider=wallet)
    agent_uri = sdk.generate_agent_uri(
        name=name, description=description,
        endpoints=[AgentEndpoint(name="repo", endpoint=endpoint, version="0.1.0")],
    )
    result = sdk.register_agent(agent_uri=agent_uri)
    tx = result.get("transactionHash")
    proof = {
        "agent": name,
        "network": "bsc-testnet",
        "chain_id": 97,
        "standard": "ERC-8004 (agent identity)",
        "sdk": "BNB AI Agent SDK (bnbagent)",
        "agent_id": result.get("agentId"),
        "wallet": address,
        "tx_hash": tx,
        "registry": REGISTRY,
        "explorer_tx": f"https://testnet.bscscan.com/tx/{tx}",
        "gas": "sponsored (MegaFuel paymaster) — gas-free testnet",
    }
    if save:
        PROOF_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROOF_PATH.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return proof


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Register VERDICT on-chain (ERC-8004, BNB AI Agent SDK).")
    ap.add_argument("--rpc", default=None, help=f"BSC testnet RPC (default {DEFAULT_RPC})")
    ap.add_argument("--no-save", action="store_true", help="don't write submission/onchain_identity.json")
    args = ap.parse_args(argv)
    proof = register(rpc=args.rpc, save=not args.no_save)
    print(json.dumps(proof, indent=2))
    print(f"\n✓ VERDICT registered on-chain — agentId {proof['agent_id']} · {proof['explorer_tx']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
