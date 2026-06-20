# VERDICT — Architecture

VERDICT is an LLM-authored crypto strategy engine designed to act like an honest quantitative researcher. It evaluates strategies rigorously using a multi-stage pipeline, outputting a highly-validated `AgentVerdict`.

## Data Flow

```mermaid
graph TD
    subgraph Data Layer
        CMC[CoinMarketCap Agent Hub]
        Historical[Historical Candles]
    end

    subgraph Signal Normalization
        Norm[verdict/signals]
        Norm -- "quotes, technicals" --> Sig1(Typed Signal)
        Norm -- "derivatives, globals" --> Context(Market Context & Regime)
    end

    subgraph Candidate Generation
        Gen[verdict/core/candidates.py]
        Gen -- "Momentum, Mean-Reversion, Breakout" --> Specs(StrategySpecs)
    end

    subgraph Validation Engine
        WF[Rolling Walk-Forward Backtester]
        Cost[PancakeSwap Cost Model]
        WF --> Metrics(Out-of-Sample Metrics)
        Cost --> Metrics
    end

    subgraph Selection & Decision
        Rule[Pre-Registered 3-Criterion Rule]
        Rule -- "Passes" --> Best(Best StrategySpec)
        Rule -- "Fails" --> Null(NO_TRADE)
    end

    subgraph Execution
        TWAK[Trust Wallet Agent Kit]
        BSC[BNB Chain / PancakeSwap]
    end

    CMC --> Norm
    Historical --> WF
    Sig1 --> Gen
    Context --> Gen
    Specs --> WF
    Metrics --> Rule
    Best --> TWAK
    TWAK --> BSC
```

## The 3-Layer Sponsor Stack

1. **Data & Signal Layer**: Powered by **CoinMarketCap Agent Hub**. We leverage MCP/REST to pull rich pricing, technicals, Fear & Greed, BTC dominance, funding rates, and open interest to dynamically tune strategy parameters based on market regimes.
2. **Strategy execution**: **Trust Wallet Agent Kit (TWAK)** handles the secure custody and local signing of trades, governed by strict drawdown kill-switches.
3. **Execution venue**: Trades are executed directly on the **BNB Chain** via **PancakeSwap v2** router smart contracts.
