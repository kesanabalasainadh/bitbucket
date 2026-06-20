# Best Use of CoinMarketCap Data & Signal

VERDICT integrates CoinMarketCap not just for simple price quotes, but as the foundational **regime and context layer** that dynamically adjusts our quantitative strategy generation.

We utilized four distinct endpoints from the **CoinMarketCap Agent Hub** via MCP/REST, mapping each to a critical function in our quantitative pipeline:

1. **`get_crypto_quotes_latest`**: Provides the live mark for our asset universe.
2. **`get_crypto_technical_analysis`**: Extracts RSI, MACD, EMA stacks, ATR, and ADX. These feed directly into our candidate generation rules to dynamically set entry/exit parameters.
3. **`get_global_metrics_latest`**: Extracts the Fear & Greed index and BTC dominance. We use these to explicitly define our `market_regime` (risk-on, risk-off, or neutral).
4. **`get_global_crypto_derivatives_metrics`**: Extracts funding rates and open interest, acting as an advanced quality filter for derivatives-heavy assets.

### Depth Over Breadth

By feeding rich CMC context into `verdict/core/candidates.py`, the engine generates smarter StrategySpecs. For example, in a "risk-off" regime (determined via CMC's Fear & Greed), the candidate generator automatically tightens trend filters, requires deeper oversold RSI entries, and reduces position sizing.

Finally, we built a robust `CMCClient` wrapper (`verdict/signals/cmc.py`) with network-retry logic and graceful degradation to offline fixtures, ensuring the agent remains operational even if certain endpoints are gated by the Basic tier. This represents a deeply integrated, production-ready usage of the CMC ecosystem.
