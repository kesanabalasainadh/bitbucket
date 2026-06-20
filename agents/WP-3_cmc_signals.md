# WP-3 — CMC Signals adapter

**You own:** `verdict/signals/` · **Branch:** `wp-3-cmc-signals` · **Independent** (start immediately).
**Goal:** one `CMCClient` that wraps the CoinMarketCap Agent Hub behind the `CONTRACTS.md` interface and
produces normalized `Signal` and `OHLCVSeries` objects. Feeds **both** tracks.

## Read first
`docs/API_REFERENCE.md` §1 (MCP/REST/x402, the 12 tools, headers), `CONTRACTS.md` (WP-3 signatures),
`verdict/schema.py`.

## Tasks
1. **`verdict/signals/cmc.py`** — `CMCClient` with methods from CONTRACTS: `quotes`, `technicals`,
   `derivatives`, `global_metrics`, `ohlcv`. Three transports behind one class, chosen by config:
   - **MCP** (default): POST to `https://mcp.coinmarketcap.com/mcp`, header `X-CMC-MCP-API-KEY`. Call
     the 12 tools (`get_crypto_quotes_latest`, `get_crypto_technical_analysis`, `get_global_metrics_latest`,
     `get_global_crypto_derivatives_metrics`, `search_cryptos`, …).
   - **REST** fallback: `https://pro-api.coinmarketcap.com`, header `X-CMC_PRO_API_KEY`.
   - **x402** (optional, keyless): `https://mcp.coinmarketcap.com/x402/mcp` — implement only if time allows;
     sign EIP-3009 with `eth-account`. Gate behind a flag.
2. **`verdict/signals/normalize.py`** — `build_signal(symbol, client) -> Signal`. Map CMC fields into the
   `Signal` schema: price, indicators{rsi,macd,ema_20/50/100,atr,adx}, funding_rate, open_interest,
   fear_greed, btc_dominance, regime (derive: risk_on/off from Fear&Greed + BTC trend), narratives.
3. **`verdict/signals/ohlcv.py`** — implement `CMCClient.ohlcv()` returning `OHLCVSeries` (CMC
   `ohlcv/historical` or DEX OHLCV). If CMC history is too shallow for the timeframe, fall back to the
   CCXT loader (coordinate with WP-1's `load_ohlcv`) and tag `source` accordingly.
4. **Resilience** — timeouts, retry/backoff, and a `fixtures/` mode: cached JSON responses so the whole
   thing is unit-testable **without a key** (WP-1/WP-2 depend on this for offline dev).
5. **Tests** `verdict/signals/tests/` — parse fixtures into valid `Signal`/`OHLCVSeries`; assert schema
   validation passes; assert regime derivation logic.

## Acceptance
- `python -m verdict.signals.cmc --symbol BNB/USDT` prints a valid `Signal` JSON (live with a key, or
  from fixtures with `--offline`).
- All 4 core methods return typed objects; no raw CMC dicts leak past this module.

## Gotchas
- **Two different header names** — MCP uses `X-CMC-MCP-API-KEY`, REST uses `X-CMC_PRO_API_KEY`. Easy bug.
- If a tool id is rejected, call `tools/list` on the MCP endpoint and match the exact name.
- Don't block the build on a key: ship the fixtures path first so WP-1/WP-2 can integrate today.
- Map symbols carefully: CMC uses symbol/slug/id; pairs like `BNB/USDT` need splitting for quote calls.
