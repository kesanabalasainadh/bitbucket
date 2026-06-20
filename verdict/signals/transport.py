"""
verdict.signals.transport — three routes to CoinMarketCap behind one tiny interface.

    Transport.fetch(resource, params) -> raw provider JSON envelope

``resource`` is a logical name ('quotes' | 'technicals' | 'derivatives' |
'global_metrics' | 'ohlcv'); each transport maps it to its concrete call. CMCClient
(see cmc.py) normalizes the envelope, so the raw provider JSON never leaves the module.

  * OfflineTransport — reads committed JSON fixtures. Zero network, zero key. This is
    the WP-1/WP-2 dev path and what every unit test uses.
  * MCPTransport   — CMC Data MCP (default live route). Header ``X-CMC-MCP-API-KEY``.
  * RESTTransport  — CMC Pro REST (fallback). Header ``X-CMC_PRO_API_KEY``.
  * X402Transport  — keyless pay-per-call (EIP-3009 on Base). Stub, gated behind a flag.

The live transports lazy-import ``httpx`` so the offline path needs no network deps.
They wire the real endpoints + the TWO distinct header names (the classic CMC bug),
but require a key and are exercised live — unit tests cover only their header/URL
selection and the retry/backoff helper.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The famous gotcha: MCP and REST use DIFFERENT header names for the same account.
MCP_HEADER = "X-CMC-MCP-API-KEY"
REST_HEADER = "X-CMC_PRO_API_KEY"

MCP_URL = "https://mcp.coinmarketcap.com/mcp"
REST_BASE = "https://pro-api.coinmarketcap.com"
X402_URL = "https://mcp.coinmarketcap.com/x402/mcp"
# Fear & Greed lives on its own REST endpoint (not part of global-metrics).
FEAR_GREED_PATH = "/v3/fear-and-greed/latest"

# logical resource -> MCP tool id (confirm via tools/list if one is rejected)
MCP_TOOLS = {
    "quotes": "get_crypto_quotes_latest",
    "technicals": "get_crypto_technical_analysis",
    "derivatives": "get_global_crypto_derivatives_metrics",
    "global_metrics": "get_global_metrics_latest",
    "ohlcv": "get_crypto_ohlcv_historical",
}
# logical resource -> CMC Pro REST path (best-effort; tools/list / docs are authoritative)
REST_PATHS = {
    "quotes": "/v2/cryptocurrency/quotes/latest",
    "technicals": "/v1/cryptocurrency/technical-analysis/latest",
    "derivatives": "/v1/derivatives/global/metrics",
    "global_metrics": "/v1/global-metrics/quotes/latest",
    "ohlcv": "/v2/cryptocurrency/ohlcv/historical",
}


@runtime_checkable
class Transport(Protocol):
    def fetch(self, resource: str, params: dict) -> dict: ...


# --------------------------------------------------------------------------- #
# Resilience
# --------------------------------------------------------------------------- #
def retry(
    fn: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> Any:
    """Call ``fn`` with exponential backoff; re-raise the last error after ``attempts``.

    ``sleep`` is injectable so tests assert retry behaviour without real delays.
    """
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if i == attempts - 1:
                raise
            sleep(base_delay * (2 ** i))
    raise last  # pragma: no cover - loop always returns or raises


# --------------------------------------------------------------------------- #
# Offline (fixtures) — the priority path
# --------------------------------------------------------------------------- #
class OfflineTransport:
    """Serve cached JSON fixtures so the whole adapter is unit-testable without a key."""

    def __init__(self, fixtures_dir: Path | str = DEFAULT_FIXTURES):
        self.dir = Path(fixtures_dir)

    def fetch(self, resource: str, params: dict) -> dict:
        name = self._filename(resource, params)
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"no offline fixture {name!r} in {self.dir} "
                f"(offline mode needs it committed; run fixtures/_generate_ohlcv.py for candles)"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _filename(resource: str, params: dict) -> str:
        if resource == "ohlcv":
            base = str(params.get("symbol", "")).split("/")[0].upper()
            tf = params.get("timeframe", "1h")
            return f"ohlcv_{base}_{tf}.json"
        return f"{resource}.json"


# --------------------------------------------------------------------------- #
# Live transports (lazy httpx; require a key; not unit-tested live)
# --------------------------------------------------------------------------- #
def _mcp_arguments(resource: str, params: dict) -> dict:
    """Shape MCP tool arguments from logical params (best-effort field names)."""
    if resource == "quotes":
        return {"symbol": ",".join(params.get("symbols", []))}
    if resource in ("technicals",):
        return {"symbol": params.get("symbol")}
    if resource == "ohlcv":
        return {k: v for k, v in {
            "symbol": str(params.get("symbol", "")).split("/")[0].upper(),
            "interval": params.get("timeframe"),
            "time_start": params.get("start"),
            "time_end": params.get("end"),
        }.items() if v is not None}
    return {}


def _mcp_unwrap(raw: dict) -> dict:
    """Extract the data payload from an MCP tools/call result envelope."""
    result = raw.get("result", raw)
    if isinstance(result, dict):
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        content = result.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else None
            if text:
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return {"data": text}
    return result if isinstance(result, dict) else raw


class MCPTransport:
    """CMC Data MCP (default live route). JSON-RPC ``tools/call`` over POST."""

    header_name = MCP_HEADER

    def __init__(self, api_key: str, url: str = MCP_URL, *, timeout: float = 20.0, attempts: int = 3):
        if not api_key:
            raise ValueError("MCPTransport requires a CMC MCP API key (header X-CMC-MCP-API-KEY)")
        self.api_key = api_key
        self.url = url
        self.timeout = timeout
        self.attempts = attempts

    @property
    def headers(self) -> dict:
        return {self.header_name: self.api_key,
                "Content-Type": "application/json", "Accept": "application/json"}

    def fetch(self, resource: str, params: dict) -> dict:
        import httpx  # lazy: offline path needs no network deps

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": MCP_TOOLS[resource], "arguments": _mcp_arguments(resource, params)}}

        def call() -> dict:
            resp = httpx.post(self.url, json=payload, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        return _mcp_unwrap(retry(call, attempts=self.attempts))


class RESTTransport:
    """CMC Pro REST (fallback). Header ``X-CMC_PRO_API_KEY``."""

    header_name = REST_HEADER

    def __init__(self, api_key: str, base: str = REST_BASE, *, timeout: float = 20.0, attempts: int = 3):
        if not api_key:
            raise ValueError("RESTTransport requires a CMC Pro API key (header X-CMC_PRO_API_KEY)")
        self.api_key = api_key
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.attempts = attempts

    @property
    def headers(self) -> dict:
        return {self.header_name: self.api_key, "Accept": "application/json"}

    def fetch(self, resource: str, params: dict) -> dict:
        import httpx  # lazy

        url = self.base + REST_PATHS[resource]
        query = self._query(resource, params)

        def call() -> dict:
            resp = httpx.get(url, params=query, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        env = retry(call, attempts=self.attempts)
        if resource == "global_metrics":
            env = self._augment_fear_greed(env)
        return env

    def _augment_fear_greed(self, env: dict) -> dict:
        """Merge the separate Fear & Greed endpoint into the global-metrics envelope.

        global-metrics carries BTC dominance but NOT Fear & Greed (that's a distinct
        /v3 endpoint). Best-effort: a failure here still leaves btc_dominance intact.
        """
        import httpx
        try:
            resp = httpx.get(self.base + FEAR_GREED_PATH, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            value = (resp.json().get("data") or {}).get("value")
            if value is not None and isinstance(env.get("data"), dict):
                env["data"]["fear_and_greed"] = {"value": value}
        except Exception:
            pass
        return env

    @staticmethod
    def _query(resource: str, params: dict) -> dict:
        if resource == "quotes":
            return {"symbol": ",".join(params.get("symbols", []))}
        if resource == "technicals":
            return {"symbol": params.get("symbol")}
        if resource == "ohlcv":
            return {k: v for k, v in {
                "symbol": str(params.get("symbol", "")).split("/")[0].upper(),
                "interval": params.get("timeframe"),
                "time_start": params.get("start"),
                "time_end": params.get("end"),
            }.items() if v is not None}
        return {}


class X402Transport:
    """Keyless pay-per-call (USDC on Base, EIP-3009). Stub — gated until signing lands."""

    header_name = "PAYMENT-SIGNATURE"

    def __init__(self, url: str = X402_URL, *, enabled: bool = False, **_: Any):
        self.url = url
        self.enabled = enabled

    def fetch(self, resource: str, params: dict) -> dict:
        raise NotImplementedError(
            "x402 keyless transport is a stub: implement EIP-3009 transferWithAuthorization "
            "signing (eth-account) for the 402 -> PAYMENT-SIGNATURE flow, then enable it. "
            "Use offline fixtures or the MCP/REST transports for now."
        )


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def make_transport(
    kind: str = "mcp",
    *,
    api_key: Optional[str] = None,
    offline: bool = False,
    fixtures_dir: Path | str = DEFAULT_FIXTURES,
    **kwargs: Any,
) -> Transport:
    """Build a transport. ``offline=True`` (or ``kind='offline'``) wins and needs no key."""
    if offline or kind == "offline":
        return OfflineTransport(fixtures_dir)
    kind = kind.lower()
    if kind == "mcp":
        return MCPTransport(api_key=api_key or "", url=kwargs.get("url", MCP_URL))
    if kind == "rest":
        return RESTTransport(api_key=api_key or "", base=kwargs.get("base", REST_BASE))
    if kind == "x402":
        return X402Transport(url=kwargs.get("url", X402_URL), enabled=kwargs.get("enabled", False))
    raise ValueError(f"unknown transport kind {kind!r} (use mcp | rest | x402 | offline)")
