"""
verdict.identity — VERDICT's on-chain agent identity via the BNB AI Agent SDK.

Registers VERDICT as an ERC-8004 agent on BNB Smart Chain (testnet, gas-free via the
MegaFuel paymaster) so the strategy engine has a verifiable, discoverable on-chain
identity — the "on-chain piece" judges look for, without any live-trading risk.

    python -m verdict.identity.register        # register (reuses the .env key)

Import the helpers from the submodule to avoid an eager bnbagent import:
    from verdict.identity.register import register, load_proof
"""
