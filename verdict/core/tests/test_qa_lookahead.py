from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
import pytest

from verdict.schema import OHLCVBar, OHLCVSeries, StrategyMetrics, StrategySpec
from verdict.core import backtest as bt
from verdict.core.costs import CostModel

def _series(closes, *, timeframe="4h", symbol="BNB/USDT"):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(hours=4)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) + 0.5
        lo = min(o, c) - 0.5
        bars.append(OHLCVBar(ts=base + i * step, open=float(o), high=float(h),
                             low=float(lo), close=float(c), volume=1000.0))
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, bars=bars)

def test_no_lookahead_probe_with_new_operands():
    closes = [100 + 18 * math.sin(i / 6.0) + 0.25 * i for i in range(220)]
    series = _series(closes)
    
    # New V2 operands: ema_slope_20, bb_width, atr_pct
    spec = StrategySpec(
        id="qa-probe", name="QA", description="QA", assets=["BNB/USDT"], timeframe="4h",
        horizon="swing", lookback=50,
        indicators=["EMA(20)", "BollingerBands(20,2)", "ATR(14)"],
        entry_rules=["close > ema_20", "bb_width > 0.01", "atr_pct > 0.005", "ema_slope_20 > -0.1"],
        exit_rules=["max_hold=6 bars"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        position_size="risk 2% of equity per trade",
        metrics=StrategyMetrics(return_pct=0, sharpe_ratio=0, win_rate=0, max_drawdown=0, risk_score=0)
    )
    costs = CostModel(gas_usd=0.0)
    
    res1 = bt.backtest_detailed(series, spec, costs)

    cut = 140
    # Poison future bars
    poisoned = list(closes[:cut]) + [999.0 - (i % 7) for i in range(cut, len(closes))]
    series2 = _series(poisoned)
    res2 = bt.backtest_detailed(series2, spec, costs)

    def completed_before(res):
        return [(t.signal_index, t.entry_index, t.exit_index,
                 round(t.entry_price, 9), round(t.exit_price, 9), t.reason)
                for t in res.trades if t.exit_index < cut]

    assert completed_before(res1) == completed_before(res2)
