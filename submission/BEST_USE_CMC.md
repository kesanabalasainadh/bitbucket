# Best Use of CoinMarketCap Data & Signal

VERDICT integrates CoinMarketCap not just for simple price quotes, but as the foundational **regime and context layer** that dynamically adjusts our quantitative strategy generation.

We utilized four distinct endpoints from the **CoinMarketCap Agent Hub** via MCP/REST, mapping each to a critical function in our quantitative pipeline:

1. **`get_crypto_quotes_latest`**: Provides the live mark for our asset universe.
2. **`get_crypto_technical_analysis`**: Extracts RSI, MACD, EMA stacks, ATR, and ADX. These feed directly into our candidate generation rules to dynamically set entry/exit parameters.
3. **`get_global_metrics_latest`**: Extracts the Fear & Greed index and BTC dominance. We use these to explicitly define our `market_regime` (risk-on, risk-off, or neutral).
4. **`get_global_crypto_derivatives_metrics`**: Extracts funding rates and open interest, acting as an advanced quality filter for derivatives-heavy assets.

### Depth Over Breadth

By feeding rich CMC context into `verdict/core/candidates.py`, the engine generates smarter StrategySpecs — and the fields are genuinely *consumed*, not just displayed. `get_global_metrics_latest` drives two pre-registered gates in the candidate generator: Fear & Greed sets the `risk_off` regime (tighter trend filters, smaller size), and **BTC dominance ≥ 55% tightens risk and forces 3-of-3 confluence for non-BTC alts** (capital concentration into BTC bleeds alts) — each echoed verbatim into the StrategySpec `reasoning` so a judge can read the cause and effect in the output.

> Note on provenance: CMC powers the **live signal/regime layer**. The committed historical candles used for the graded, reproducible backtest are sourced from a public exchange via ccxt/kucoin (labelled `ccxt-kucoin`), so the offline run needs no CMC key.

Finally, we built a `CMCClient` wrapper (`verdict/signals/cmc.py`) with network-retry logic and graceful degradation to offline fixtures, keeping the agent operational even when endpoints are gated by the Basic tier (live-verified: quotes + global-metrics are open; technicals/derivatives/OHLCV degrade to fixtures). This is a deeply integrated, graceful-degradation usage of the CMC ecosystem.
