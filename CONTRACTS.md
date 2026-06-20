# CONTRACTS — the interfaces every VERDICT agent codes against

> **Why this file exists:** six agents build in parallel in separate sessions. They never read each
> other's internals — they agree on the **types** in [`verdict/schema.py`](verdict/schema.py) and the
> **function signatures** below. If you honor these, your module drops into the system with zero
> integration friction. If you need to change a contract, edit `schema.py` + this file in the SAME
> commit and shout in the build channel.

The data flows in one direction:

```
            WP-3 CMC signals            WP-1 quant core                     WP-2 skill
 CMC API ─► Signal / OHLCVSeries ─► backtest + walk-forward ─► StrategySpec ─► AgentVerdict ─► JSON  (TRACK 2 done)
                                            │                                      │
                                            ▼                                      ▼
                                   WP-5 runtime loop  ◄── Decision ──  strategy.decide(Signal)
                                            │
                                            ▼
                              WP-4 execution ─► Fill  (PancakeSwap / TWAK / BSC)   (TRACK 1)
```

---

## Module boundaries & signatures

Code to these exact signatures. Types are all from `verdict.schema`.

### WP-1 · `verdict/core/` — quant core (Track-2 critical path)
```python
# verdict/core/data.py
def load_ohlcv(symbol: str, timeframe: str, start, end, source="cmc") -> OHLCVSeries: ...

# verdict/core/costs.py
class CostModel:                      # crypto/DEX fees + slippage (replaces NSE cost_model)
    def round_trip_cost(self, notional_usd: float) -> float: ...
    def clears_costs(self, expected_profit_usd: float, notional_usd: float, k: float = 3.0) -> bool: ...

# verdict/core/backtest.py
def backtest(series: OHLCVSeries, spec: StrategySpec, costs: CostModel) -> StrategyMetrics: ...
    # no-lookahead: signal on bar close, fill next bar open. Returns metrics + fills curve.

# verdict/core/walkforward.py
def walk_forward(series: OHLCVSeries, spec: StrategySpec, costs: CostModel,
                 train_bars: int, test_bars: int, step_bars: int) -> list[WalkForwardWindow]: ...

# verdict/core/curves.py
def equity_drawdown(fills_or_returns) -> tuple[list[float], list[float], list[float]]:  # equity, benchmark, drawdown
```

### WP-2 · `skills/verdict-strategy/` + `verdict/core/select.py` — skill + selection
```python
# verdict/core/candidates.py
def generate_candidates(series: OHLCVSeries, signal: Signal | None) -> list[StrategySpec]: ...
    # momentum / mean-reversion / breakout, reusing the legacy entry/exit rule library

# verdict/core/select.py  (the pre-registered 3-criterion judge)
def select(candidates: list[StrategySpec], series: OHLCVSeries, costs: CostModel) -> AgentVerdict: ...
    # runs each through walk_forward, applies the committed criteria, returns TRADE or NO_TRADE
```
`skills/verdict-strategy/SKILL.md` is the Anthropic-format wrapper that orchestrates the above via
CMC tools and prints the AgentVerdict JSON. (See WP-2.)

### WP-3 · `verdict/signals/` — CMC adapter
```python
# verdict/signals/cmc.py
class CMCClient:
    def quotes(self, symbols: list[str]) -> dict[str, float]: ...
    def technicals(self, symbol: str) -> dict[str, float]: ...          # rsi, macd, ema_*, atr, adx
    def derivatives(self) -> dict: ...                                  # funding, OI, liquidations
    def global_metrics(self) -> dict: ...                               # fear_greed, btc_dominance
    def ohlcv(self, symbol, timeframe, start, end) -> OHLCVSeries: ...  # used by WP-1 load_ohlcv(source="cmc")
def build_signal(symbol: str, client: CMCClient) -> Signal: ...
```
Three transports behind one interface: **MCP** (`X-CMC-MCP-API-KEY`), **REST**
(`X-CMC_PRO_API_KEY`), **x402** (keyless, ~$0.01 USDC/call). Default MCP; fall back to REST.

### WP-4 · `verdict/execution/` — custody + execution (Track 1)
```python
# verdict/execution/base.py
class Executor(Protocol):
    def quote(self, decision: Decision) -> dict: ...
    def execute(self, decision: Decision) -> Fill: ...
    def balances(self) -> dict[str, float]: ...

# implementations: TWAKExecutor (Trust Wallet Agent Kit), PancakeExecutor (web3 router), PaperExecutor
```
`PaperExecutor` MUST exist first so WP-5 can run end-to-end before real signing works.

### WP-5 · `verdict/agent/` — runtime loop + risk governor (Track 1)
```python
# verdict/agent/governor.py
class RiskGovernor:
    def check(self, decision: Decision, state) -> tuple[bool, str]: ...   # enforce RiskLimits, kill-switch

# verdict/agent/loop.py
def run(strategy, signals: CMCClient, executor: Executor, limits: RiskLimits, mode: Mode): ...
```

### WP-6 · `submission/` — packaging. Consumes the AgentVerdict JSON + curves; writes no core code.

---

## The pre-registered selection criteria (committed BEFORE seeing results)

Borrowed verbatim in spirit from the legacy `experiments/` methodology — this honesty is the moat.
A candidate is **TRADE-eligible only if ALL three hold** on walk-forward out-of-sample windows:

1. **Beats benchmark net of costs** — median OOS `return_pct` > buy-&-hold over the same windows.
2. **Positive in ≥ 60% of windows** — not one lucky window; `sum(w.passed)/len(windows) >= 0.6`.
3. **Risk-adjusted** — `sharpe_ratio >= 1.0` AND `max_drawdown <= 25%`.

`risk_score` (0–100, higher = safer) = weighted blend of Sharpe, drawdown, win-rate, window
consistency. Exact formula lives in `verdict/core/select.py`; document it in the StrategySpec.

If **no** candidate passes → `AgentVerdict(verdict=NO_TRADE, summary="...")`. Shipping an honest null
result is a feature, not a failure — it is the credibility differentiator for Track-2 judges.

---

## StrategySpec JSON — example shape the skill must emit

```json
{
  "id": "momentum-bnb-4h-v1",
  "name": "BNB 4h Momentum Pullback",
  "description": "EMA-stack trend + pullback entry on BNB/USDT, ATR exits.",
  "assets": ["BNB/USDT"], "timeframe": "4h", "horizon": "swing (2-10 bars)", "lookback": 120,
  "risk_profile": "balanced",
  "indicators": ["EMA(20)","EMA(50)","EMA(100)","RSI(14)","MACD","ATR(14)"],
  "entry_rules": ["close>EMA100","EMA20>EMA50","close within 2% of EMA20","MACD hist rising","RSI in [40,65]"],
  "exit_rules": ["stop=entry-1.5*ATR","target=entry+3*ATR","max_hold=10 bars"],
  "stop_loss": "1.5 * ATR(14)", "take_profit": "3.0 * ATR(14)", "position_size": "risk 2% equity/trade",
  "risk_limits": {"max_drawdown_pct": 25, "max_position_pct": 20},
  "metrics": {"return_pct": 31.2,"sharpe_ratio": 1.4,"win_rate": 0.46,"max_drawdown": 17.8,
              "risk_score": 72,"num_trades": 38},
  "walkforward": [ {"test_start":"...","test_end":"...","metrics":{...},"passed":true} ],
  "equity_curve": [1.0, 1.02, ...], "benchmark_curve": [1.0, 1.01, ...], "drawdown_curve": [0, -0.01, ...],
  "reasoning": "Trend+pullback survived 5/7 OOS windows; funding-rate filter cut whipsaws.",
  "confidence": 0.62, "market_regime": "risk_on",
  "data_source": "cmc + ccxt-binance", "cost_model": "PancakeSwap v2 0.25% + 30bps slippage",
  "version": "0.1.0"
}
```

Produce it from code with `spec.stamp().model_dump_json(indent=2)`.
