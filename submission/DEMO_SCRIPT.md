# VERDICT — Demo Script (2-3 mins)

**Goal:** Prove the rigor, reproducibility, and honesty of VERDICT.

## 0:00 - Introduction & The Problem
- **Visual**: Show the VERDICT logo and BUIDL page.
- **Script**: "Welcome to VERDICT. Most AI trading agents use a single prompt and one lucky backtest window to generate 'market-beating' strategies. VERDICT is built to be the opposite: an honest quant that treats strategy generation as rigorous research."

## 0:30 - The Data Engine (CoinMarketCap)
- **Visual**: Show `verdict/signals/cmc.py` pulling MCP tools.
- **Script**: "It starts by pulling rich live context from the CoinMarketCap Agent Hub—technicals, funding rates, and Fear & Greed—to determine the current market regime."

## 1:00 - Walk-Forward Validation & DEX Costs
- **Visual**: Run the main reproducible CLI command: `python -m verdict.core.select --assets BNB/USDT,CAKE/USDT,BTC/USDT,ETH/USDT --tf 4h`
- **Script**: "We don't just backtest once. VERDICT generates multiple candidates and runs them through a strict, no-lookahead rolling walk-forward validation. We also apply a realistic PancakeSwap DEX cost model on every trade."

## 1:30 - The Pre-Registered Rule (Honesty)
- **Visual**: Highlight the `NO_TRADE` output JSON on the screen.
- **Script**: "Here is the moat. We apply a pre-registered 3-criterion rule. If no strategy clears the hurdle net of costs, VERDICT honestly outputs `NO_TRADE`. It will never force a bad trade."

## 2:00 - Execution (Track 1 Stretch)
- **Visual**: Show `skills/verdict-strategy/examples/equity_curve.png` and then briefly show `verdict/agent/` execution loop.
- **Script**: "When a strategy *does* survive, the `AgentVerdict` JSON is handed to a Trust Wallet Agent Kit execution loop, trading securely on PancakeSwap/BNB Chain, governed by a hard drawdown kill-switch. Thank you for watching!"
