# QA Findings & Hardening Report — WP-3 (CMC Signals)

This report documents the verification and hardening of the CoinMarketCap signals layer on the `qa/wp3-signals-hardening-v2` branch.

## 1. API Subscription Tier & Endpoint Audit

We performed live verification of the CoinMarketCap API using the provided credentials (a Basic subscription tier key).

### Endpoint Expositions and Gates
| Endpoint Path | Description | Access on Basic Tier | Action Taken |
|---|---|---|---|
| `/v2/cryptocurrency/quotes/latest` | Crypto quotes | **Allowed** (200 OK) | Fetched live |
| `/v1/global-metrics/quotes/latest` | Global market metrics | **Allowed** (200 OK) | Fetched live |
| `/v1/cryptocurrency/technical-analysis/latest` | Technical indicators | **Not Found (404)** / Gated | Gracefully degraded to fixtures |
| `/v1/derivatives/global/metrics` | Derivatives metrics | **Not Found (404)** / Gated | Gracefully degraded to fixtures |
| `/v2/cryptocurrency/ohlcv/historical` | Historical OHLCV | **Gated (403 Forbidden)** | Gracefully degraded to fixtures |

### WAF Block on MCP Endpoint
When invoking the Model Context Protocol (MCP) endpoint (`https://mcp.coinmarketcap.com/mcp`), the CloudFront Web Application Firewall (WAF) blocks any HTTP POST requests containing the JSON-RPC key `"jsonrpc"`, returning a `400 Bad Request`. Because MCP requires this JSON-RPC format, standard MCP POST requests fail unless using a transport with SSE channel resolution or compressed formats. To ensure absolute resilience, the client automatically handles this by flagging the failure and reverting to robust offline fixtures.

---

## 2. Hardening Measures Implemented

1. **Graceful Degradation (`_fetch_with_fallback`)**:
   - Wrapped all `CMCClient` endpoint fetch calls in a robust fallback mechanism. If a live call fails (due to 400 Bad Request WAF blocks, 403 Forbidden tier gates, or 404 Not Found unavailable paths), the client catches the error, emits a warning, sets `client.degraded = True`, and seamlessly pulls the required data from local, pre-recorded fixtures.
   
2. **Signal Provenance Marking**:
   - The `build_signal` pipeline in [normalize.py](file:///D:/Antigravity/BNB%20Hackathon/github%20code/verdict/signals/normalize.py) detects the client's degraded status. When falling back to fixtures under live operation, the Signal source is dynamically appended with `-degraded` (e.g., `cmc-mcp-degraded` or `cmc-rest-degraded`), making the degradation transparent.

3. **Deterministic Timestamps**:
   - Kept `build_signal` deterministic by accepting an optional injectable `ts: Optional[datetime] = None`. When doing live data fetching, it correctly defaults to the current UTC timezone-aware datetime, ensuring it never corrupts backtest logic.

4. **Dynamic Environment Variable Loading**:
   - Added automatic `load_dotenv()` integration inside `CMCClient.from_env()` and the main CLI block. This guarantees `.env` files are parsed and environment variables are loaded correctly when invoking CLI commands or unit tests.

5. **Pytest CLI integration (`--live`)**:
   - Configured custom pytest hooks in [conftest.py](file:///D:/Antigravity/BNB%20Hackathon/github%20code/verdict/signals/tests/conftest.py) to register the `@pytest.mark.live` decorator. Live integration tests are collected but safely skipped by default, preventing execution failure when keys are absent. They can be explicitly executed by appending `--live` in the command.

---

## 3. Bug Audit Outside signals/

No bugs were found in external layers (`verdict/core/`, etc.). All 100 test cases across the entire codebase are green.

---

## 4. Test Verification Checklist

- **Offline test suite**: `python -m pytest verdict/signals -q` -> **32 Passed, 2 Skipped** (0.36s)
- **Live test suite**: `python -m pytest verdict/signals --live -q` -> **34 Passed** (12.88s)
- **Full test suite**: `python -m pytest verdict -q` -> **100 Passed, 3 Skipped** (16.60s)
- **CLI offline run**: `python -m verdict.signals.cmc --symbol BNB/USDT --offline` -> **Succeeded (valid JSON)**
- **CLI online fallback run**: `python -m verdict.signals.cmc --symbol BNB/USDT` -> **Succeeded (graceful degradation logged, valid JSON printed)**
