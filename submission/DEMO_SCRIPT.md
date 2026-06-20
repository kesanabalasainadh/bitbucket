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

## 1:30 - Two-Sided: the Pre-Registered Rule (Honesty)
- **Visual**: Run `python skills/verdict-strategy/scripts/two_sided_demo.py` — show the regime table (each archetype acts only in its regime; **0 trades in a downtrend**), the genuine `TRADE` on the controlled validated-edge market, and the honest `NO_TRADE` on the real majors.
- **Script**: "Here is the moat — VERDICT is two-sided. We apply a pre-registered 3-criterion rule out-of-sample, net of DEX costs. When a candidate genuinely clears it — like this range strategy that beat buy-and-hold in 100% of walk-forward windows — VERDICT issues a `TRADE` with full evidence. When nothing clears it, as on the real BSC majors, it honestly outputs `NO_TRADE`. It never forces a bad trade, and it never hides a real edge."

## 2:00 - The Agent Layer (decision matrix · kill-switch · DCA narrative)
- **Visual**: Show `verdict/core/matrix.py` (TRADE/WAIT/DCA/NO_TRADE), `verdict/safety/kill_switch.py`, and `skills/verdict-strategy/examples/TRADE_equity.png`.
- **Script**: "The `AgentVerdict` feeds an explainable decision matrix, a hard-drawdown kill-switch, and a sentiment-aware DCA agent with **zero execution authority** — it explains, it never signs. Live PancakeSwap / Trust Wallet execution is Track-1 future work, deliberately not in this codebase. Everything you saw is deterministic and reproducible from a clean clone with no API key. Thank you for watching!"
