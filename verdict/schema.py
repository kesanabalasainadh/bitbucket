"""
VERDICT — shared data contracts (the single source of truth for ALL work packages).

Every module codes against THESE types. Do not redefine them locally; import from here:

    from verdict.schema import OHLCVSeries, Signal, StrategySpec, AgentVerdict, Decision, Fill

Design rules:
  * Pydantic v2 BaseModels → free validation + `.model_dump_json()` for the Track-2 deliverable.
  * Everything that crosses a module boundary (signal -> strategy -> backtest -> verdict ->
    decision -> execution) is one of the models below.
  * The StrategySpec MUST be deterministic and JSON-exportable (judges inspect/compare/backtest it).

See ../CONTRACTS.md for prose, examples, and the per-WP responsibility matrix.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class Verdict(str, Enum):
    TRADE = "TRADE"          # a candidate passed the pre-registered criteria
    NO_TRADE = "NO_TRADE"    # honest null result — no edge after costs


class Mode(str, Enum):
    PAPER = "paper"
    TESTNET = "testnet"
    MAINNET = "mainnet"


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
class OHLCVBar(BaseModel):
    ts: datetime                       # bar OPEN time, tz-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVSeries(BaseModel):
    """A candle series for one symbol/timeframe. The backtester's primary input."""
    symbol: str                        # e.g. "BNB/USDT"
    timeframe: str                     # e.g. "1h", "4h", "1d"
    source: str = "cmc"                # cmc | ccxt-binance | ...
    bars: list[OHLCVBar] = Field(default_factory=list)

    def to_dataframe(self):            # pandas imported lazily to keep schema import cheap
        import pandas as pd
        df = pd.DataFrame([b.model_dump() for b in self.bars])
        if not df.empty:
            df = df.set_index("ts").sort_index()
        return df


class Signal(BaseModel):
    """A normalized, point-in-time market snapshot produced by the CMC adapter (WP-3).

    This is the *live signal* surface — distinct from historical OHLCV used for backtesting.
    Strategy code reads these fields; it must never reach back into raw CMC JSON.
    """
    ts: datetime
    symbol: str
    price: float
    # technicals (from CMC get_crypto_technical_analysis or computed locally)
    indicators: dict[str, float] = Field(default_factory=dict)   # rsi, macd, macd_signal, ema_20, ema_50, ema_100, atr, adx ...
    # derivatives (CMC get_global_crypto_derivatives_metrics)
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    # market context (CMC get_global_metrics_latest)
    fear_greed: Optional[float] = None
    btc_dominance: Optional[float] = None
    regime: Optional[str] = None       # e.g. "risk_on" | "risk_off" | "neutral"
    narratives: list[str] = Field(default_factory=list)
    source: str = "cmc-mcp"


# --------------------------------------------------------------------------- #
# Strategy + backtest results  (Track 2 deliverable core)
# --------------------------------------------------------------------------- #
class StrategyMetrics(BaseModel):
    return_pct: float                  # total return over the test window, %
    sharpe_ratio: float
    win_rate: float                    # 0..1
    max_drawdown: float                # %, positive number (e.g. 18.4 == -18.4%)
    risk_score: float                  # 0..100, our composite (see CONTRACTS.md)
    num_trades: int = 0
    sortino_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    exposure_pct: Optional[float] = None
    # sizing/risk knobs echoed for convenience (judges expect these on the spec)
    position_size: Optional[float] = None    # fraction of equity per trade, 0..1
    stop_loss: Optional[float] = None        # as ATR mult or % (state which in CONTRACTS)
    take_profit: Optional[float] = None


class WalkForwardWindow(BaseModel):
    """One rolling out-of-sample window — VERDICT's differentiator vs single-shot backtests."""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    metrics: StrategyMetrics
    passed: bool = False               # did this window clear the per-window bar?


class StrategySpec(BaseModel):
    """THE Track-2 deliverable. Deterministic, inspectable, comparable, backtestable, exportable.

    Emit one per candidate; the winner is wrapped in an AgentVerdict.
    """
    id: str
    name: str
    description: str
    # universe / horizon
    assets: list[str]                  # e.g. ["BNB/USDT", "CAKE/USDT"]
    timeframe: str                     # "1h" | "4h" | "1d"
    horizon: str                       # human: "swing (2-10 bars)"
    lookback: int                      # bars of history the rules need
    risk_profile: RiskProfile = RiskProfile.BALANCED
    # the actual rules (deterministic, human-readable, machine-checkable)
    indicators: list[str] = Field(default_factory=list)
    entry_rules: list[str] = Field(default_factory=list)
    exit_rules: list[str] = Field(default_factory=list)
    stop_loss: str = ""                # e.g. "1.5 * ATR(14)"
    take_profit: str = ""              # e.g. "3.0 * ATR(14)"
    position_size: str = ""            # e.g. "risk 2% of equity per trade"
    risk_limits: dict[str, Any] = Field(default_factory=dict)
    # evidence
    metrics: StrategyMetrics
    walkforward: list[WalkForwardWindow] = Field(default_factory=list)
    equity_curve: list[float] = Field(default_factory=list)
    benchmark_curve: list[float] = Field(default_factory=list)   # buy & hold
    drawdown_curve: list[float] = Field(default_factory=list)
    # agent rationale
    reasoning: str = ""
    confidence: float = 0.0            # 0..1
    market_regime: str = ""
    # provenance
    data_source: str = "cmc"
    cost_model: str = ""               # e.g. "PancakeSwap v2: 0.25% fee + 30bps slippage"
    version: str = "0.1.0"
    created_at: Optional[datetime] = None

    def stamp(self) -> "StrategySpec":
        """Call from non-workflow code to set created_at (workflows can't use Date.now)."""
        self.created_at = datetime.now(timezone.utc)
        return self


class AgentVerdict(BaseModel):
    """VERDICT's honest output: pick the best risk-adjusted candidate, or declare no edge."""
    verdict: Verdict
    selected: Optional[StrategySpec] = None
    candidates: list[StrategySpec] = Field(default_factory=list)
    rejected: dict[str, str] = Field(default_factory=dict)        # candidate_id -> why rejected
    criteria: dict[str, Any] = Field(default_factory=dict)        # the pre-registered 3-criterion results
    summary: str = ""                  # plain-English verdict for the demo/judges


# --------------------------------------------------------------------------- #
# Live trading  (Track 1 runtime — WP-4 / WP-5)
# --------------------------------------------------------------------------- #
class RiskLimits(BaseModel):
    max_drawdown_pct: float = 25.0     # hard kill-switch (hackathon DQ example: 30%)
    max_position_pct: float = 20.0
    daily_loss_limit_pct: float = 8.0
    max_open_positions: int = 3
    slippage_bps_max: int = 80
    min_trades_per_day: int = 1        # Track-1 min-trade-count rule
    token_allowlist: list[str] = Field(default_factory=list)      # BEP-20 allowlist (~149)


class Decision(BaseModel):
    """Strategy -> runtime. What the brain wants to do, before execution/risk gating."""
    ts: datetime
    symbol: str
    side: Side
    size_usd: float = 0.0
    order_type: str = "market"         # market | limit
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""
    confidence: float = 0.0
    strategy_id: str = ""


class Fill(BaseModel):
    """Execution result from the TWAK/PancakeSwap adapter (WP-4)."""
    decision_ts: datetime
    symbol: str
    side: Side
    venue: str = "pancakeswap"         # pancakeswap | bsc-perps | twak
    amount_in: float = 0.0
    amount_out: float = 0.0
    price: float = 0.0
    slippage_bps: Optional[float] = None
    tx_hash: Optional[str] = None
    gas_used: Optional[int] = None
    status: str = "filled"             # filled | reverted | rejected | simulated
    error: Optional[str] = None
    ts: Optional[datetime] = None


__all__ = [
    "Side", "RiskProfile", "Verdict", "Mode",
    "OHLCVBar", "OHLCVSeries", "Signal",
    "StrategyMetrics", "WalkForwardWindow", "StrategySpec", "AgentVerdict",
    "RiskLimits", "Decision", "Fill",
]
