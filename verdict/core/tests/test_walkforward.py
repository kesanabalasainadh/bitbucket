"""TDD for verdict.core.walkforward — rolling out-of-sample validation.

VERDICT's differentiator vs single-shot backtests: a fixed StrategySpec is replayed
across many rolling windows, each scored ONLY on its out-of-sample test region and
compared to buy-&-hold over that same region, net of costs. ``passed`` records
whether the strategy beat the benchmark that window.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from verdict.schema import OHLCVBar, OHLCVSeries, StrategyMetrics, StrategySpec, WalkForwardWindow
from verdict.core import walkforward as wf
from verdict.core.costs import CostModel


def _series(closes, timeframe="4h"):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(hours=4)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        bars.append(OHLCVBar(ts=base + i * step, open=float(o), high=max(o, c) + 0.5,
                             low=min(o, c) - 0.5, close=float(c), volume=1000.0))
    return OHLCVSeries(symbol="BNB/USDT", timeframe=timeframe, bars=bars)


def _spec():
    return StrategySpec(
        id="wf", name="wf", description="wf", assets=["BNB/USDT"], timeframe="4h",
        horizon="swing", lookback=50, indicators=["EMA(20)", "EMA(50)", "ATR(14)"],
        entry_rules=["close > ema_20", "ema_20 > ema_50"],
        exit_rules=["max_hold=8 bars"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        position_size="risk 2% of equity per trade",
        metrics=StrategyMetrics(return_pct=0, sharpe_ratio=0, win_rate=0,
                                max_drawdown=0, risk_score=0),
    )


def _trend_series(n=1000):
    return [100.0 * (1.0025 ** i) + 8.0 * math.sin(i / 9.0) for i in range(n)]


def test_walk_forward_returns_at_least_three_windows_with_passed_flags():
    series = _series(_trend_series())
    windows = wf.walk_forward(series, _spec(), CostModel(gas_usd=0.0),
                              train_bars=200, test_bars=100, step_bars=100)
    assert len(windows) >= 3
    for w in windows:
        assert isinstance(w, WalkForwardWindow)
        assert isinstance(w.passed, bool)
        assert isinstance(w.metrics, StrategyMetrics)
        assert w.train_start < w.train_end <= w.test_start < w.test_end


def test_window_count_matches_geometry():
    n = 1000
    series = _series(_trend_series(n))
    train, test, step = 200, 100, 100
    windows = wf.walk_forward(series, _spec(), CostModel(gas_usd=0.0), train, test, step)
    expected = (n - train - test) // step + 1
    assert len(windows) == expected


def test_detailed_aligns_windows_and_returns_and_passed_rule():
    series = _series(_trend_series())
    detail = wf.walk_forward_detailed(series, _spec(), CostModel(gas_usd=0.0),
                                      train_bars=200, test_bars=100, step_bars=100)
    assert len(detail.windows) == len(detail.strategy_returns) == len(detail.benchmark_returns)
    for w, sr, br in zip(detail.windows, detail.strategy_returns, detail.benchmark_returns):
        # passed iff strategy beat buy-&-hold over that OOS window
        assert w.passed == (sr > br)
        assert w.metrics.return_pct == sr


def test_walk_forward_is_deterministic():
    series = _series(_trend_series())
    spec, costs = _spec(), CostModel(gas_usd=0.0)
    a = wf.walk_forward(series, spec, costs, 200, 100, 100)
    b = wf.walk_forward(series, spec, costs, 200, 100, 100)
    assert [(w.passed, w.metrics.return_pct) for w in a] == \
           [(w.passed, w.metrics.return_pct) for w in b]


def test_short_series_yields_no_windows_gracefully():
    series = _series(_trend_series(120))
    windows = wf.walk_forward(series, _spec(), CostModel(gas_usd=0.0),
                              train_bars=200, test_bars=100, step_bars=100)
    assert windows == []
