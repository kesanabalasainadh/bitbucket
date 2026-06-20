"""
verdict.signals.cmc — one CMCClient over MCP (default) / REST (fallback) / x402 (stub)
/ offline fixtures, exposing the CONTRACTS.md WP-3 surface:

    CMCClient.quotes / technicals / derivatives / global_metrics / ohlcv
    build_signal(symbol, client) -> Signal        (re-exported from normalize)

Every CMC envelope is normalized into typed/primitive outputs here; raw provider
JSON never leaves this module. CLI:  python -m verdict.signals.cmc --symbol BNB/USDT --offline
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from verdict.schema import OHLCVSeries
from verdict.signals.ohlcv import parse_ohlcv
from verdict.signals.symbols import base_symbol
from verdict.signals.transport import DEFAULT_FIXTURES, Transport, make_transport

# canonical Signal indicator key -> accepted CMC field aliases
_TA_ALIASES = {
    "rsi": ("rsi", "rsi_14"),
    "macd": ("macd",),
    "macd_signal": ("macd_signal", "macd_sig"),
    "ema_20": ("ema_20", "ema20"),
    "ema_50": ("ema_50", "ema50"),
    "ema_100": ("ema_100", "ema100"),
    "atr": ("atr", "atr_14"),
    "adx": ("adx", "adx_14"),
}


# --------------------------------------------------------------------------- #
# Normalizers (CMC REST/MCP envelope -> typed primitives)
# --------------------------------------------------------------------------- #
def _quote_price(entry) -> Optional[float]:
    if isinstance(entry, list):              # CMC v2 returns data[sym] as a list
        entry = entry[0] if entry else {}
    usd = (entry.get("quote") or {}).get("USD") or {}
    price = usd.get("price")
    return float(price) if price is not None else None


def _parse_quotes(env: dict, requested: list[str]) -> dict[str, float]:
    data = env.get("data", env) or {}
    out: dict[str, float] = {}
    for sym in requested:
        base = base_symbol(sym)
        entry = data.get(base) or data.get(sym) or data.get(base.lower())
        if entry is not None:
            price = _quote_price(entry)
            if price is not None:
                out[sym] = price
    return out


def _parse_technicals(env: dict, symbol: str) -> dict[str, float]:
    data = env.get("data", env) or {}
    base = base_symbol(symbol)
    node = data.get(base) or data.get(symbol) or data
    ind = node.get("indicators") if isinstance(node, dict) else None
    ind = ind if isinstance(ind, dict) else (node if isinstance(node, dict) else {})
    out: dict[str, float] = {}
    for canon, aliases in _TA_ALIASES.items():
        for alias in aliases:
            if ind.get(alias) is not None:
                out[canon] = float(ind[alias])
                break
    return out


def _parse_global_metrics(env: dict) -> dict[str, float]:
    data = env.get("data", env) or {}
    out: dict[str, float] = {}
    fng = data.get("fear_and_greed", data.get("fear_greed"))
    if isinstance(fng, dict):
        fng = fng.get("value")
    if fng is not None:
        out["fear_greed"] = float(fng)
    for key in ("btc_dominance", "eth_dominance"):
        if data.get(key) is not None:
            out[key] = float(data[key])
    usd = (data.get("quote") or {}).get("USD") or {}
    for key in ("total_market_cap", "total_volume_24h"):
        if usd.get(key) is not None:
            out[key] = float(usd[key])
    return out


def _floats(d) -> dict[str, float]:
    return {k: float(v) for k, v in (d or {}).items() if v is not None}


def _parse_derivatives(env: dict) -> dict:
    data = env.get("data", env) or {}
    return {
        "funding_rate": _floats(data.get("funding_rate")),
        "open_interest": _floats(data.get("open_interest")),
        "liquidations_24h": _floats(data.get("liquidations_24h")),
    }


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class CMCClient:
    """Wraps a Transport and returns normalized, typed data only."""

    def __init__(
        self,
        transport: Optional[Transport] = None,
        *,
        offline: bool = False,
        kind: str = "mcp",
        api_key: Optional[str] = None,
        fixtures_dir=None,
    ):
        if transport is None:
            transport = make_transport(
                kind=kind, api_key=api_key, offline=offline,
                fixtures_dir=fixtures_dir or DEFAULT_FIXTURES,
            )
        self.transport = transport

    @classmethod
    def offline(cls, fixtures_dir=None) -> "CMCClient":
        """Fixtures-backed client — no network, no key (WP-1/WP-2 dev + all tests)."""
        return cls(offline=True, fixtures_dir=fixtures_dir)

    @classmethod
    def from_env(cls, env=None) -> "CMCClient":
        """Default MCP, fall back to REST, by which key is present. No key -> offline."""
        env = env if env is not None else os.environ
        if env.get("CMC_MCP_API_KEY"):
            return cls(kind="mcp", api_key=env["CMC_MCP_API_KEY"])
        if env.get("CMC_PRO_API_KEY"):
            return cls(kind="rest", api_key=env["CMC_PRO_API_KEY"])
        return cls(offline=True)

    # --- CONTRACTS.md WP-3 surface ---------------------------------------- #
    def quotes(self, symbols: list[str]) -> dict[str, float]:
        env = self.transport.fetch("quotes", {"symbols": [base_symbol(s) for s in symbols]})
        return _parse_quotes(env, symbols)

    def technicals(self, symbol: str) -> dict[str, float]:
        env = self.transport.fetch("technicals", {"symbol": base_symbol(symbol)})
        return _parse_technicals(env, symbol)

    def derivatives(self) -> dict:
        return _parse_derivatives(self.transport.fetch("derivatives", {}))

    def global_metrics(self) -> dict:
        return _parse_global_metrics(self.transport.fetch("global_metrics", {}))

    def ohlcv(self, symbol: str, timeframe: str, start=None, end=None) -> OHLCVSeries:
        env = self.transport.fetch(
            "ohlcv", {"symbol": symbol, "timeframe": timeframe, "start": start, "end": end}
        )
        return parse_ohlcv(env, symbol, timeframe)


# build_signal lives in normalize.py; re-export so the CONTRACTS path
# `from verdict.signals.cmc import build_signal` also resolves.
from verdict.signals.normalize import build_signal  # noqa: E402


# --------------------------------------------------------------------------- #
# CLI:  python -m verdict.signals.cmc --symbol BNB/USDT --offline
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print a normalized VERDICT Signal for a symbol.")
    parser.add_argument("--symbol", default="BNB/USDT", help="market pair, e.g. BNB/USDT")
    parser.add_argument("--offline", action="store_true",
                        help="use committed fixtures (no key, no network)")
    parser.add_argument("--transport", default="mcp", choices=["mcp", "rest", "x402"],
                        help="live transport when not --offline")
    args = parser.parse_args(argv)

    if args.offline:
        client = CMCClient.offline()
    elif os.environ.get("CMC_MCP_API_KEY") or os.environ.get("CMC_PRO_API_KEY"):
        client = CMCClient.from_env()
    else:
        client = CMCClient(kind=args.transport, api_key=os.environ.get("CMC_PRO_API_KEY"))

    signal = build_signal(args.symbol, client)
    print(signal.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
