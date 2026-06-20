"""
verdict.core.walkforward — rolling out-of-sample (walk-forward) validation.

This is VERDICT's credibility engine. A single backtest is easy to overfit; a
strategy that only survives ONE lucky window is noise. So we replay a FIXED
StrategySpec across many rolling windows and score each ONLY on its out-of-sample
test region, net of costs, against buy-&-hold over that same region.

Geometry (all in bars):
    window k:  train = bars[i : i+train_bars]      (indicator warmup / context)
               test  = bars[i+train_bars : i+train_bars+test_bars]   (scored, OOS)
               i advances by step_bars each window.

The spec is never re-fit per window (the rules are committed up front), so the
train region is pure warmup — trading and every metric are confined to the test
region via the backtester's ``trade_start`` (= train_bars within the slice).
``passed`` = the strategy's net OOS return beat buy-&-hold that window.

    walk_forward(...)          -> list[WalkForwardWindow]
    walk_forward_detailed(...) -> WalkForwardDetail(windows, strategy_returns,
                                                    benchmark_returns)   (for select.py)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from verdict.schema import OHLCVSeries, StrategySpec, WalkForwardWindow
from verdict.core.backtest import backtest_detailed
from verdict.core.costs import CostModel


@dataclass
class WalkForwardDetail:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    strategy_returns: list[float] = field(default_factory=list)   # per-window OOS return %
    benchmark_returns: list[float] = field(default_factory=list)  # per-window buy&hold %


def walk_forward_detailed(
    series: OHLCVSeries,
    spec: StrategySpec,
    costs: CostModel,
    train_bars: int,
    test_bars: int,
    step_bars: int,
) -> WalkForwardDetail:
    bars = sorted(series.bars, key=lambda b: b.ts)
    n = len(bars)
    detail = WalkForwardDetail()
    if train_bars < 1 or test_bars < 2 or step_bars < 1:
        return detail

    i = 0
    while i + train_bars + test_bars <= n:
        slice_bars = bars[i:i + train_bars + test_bars]
        sub = OHLCVSeries(symbol=series.symbol, timeframe=series.timeframe,
                          source=series.source, bars=slice_bars)
        # Trade only in the OOS test region; the train region is indicator warmup.
        res = backtest_detailed(sub, spec, costs, trade_start=train_bars)
        m = res.metrics

        test_closes = [b.close for b in slice_bars[train_bars:]]
        bench_ret = (test_closes[-1] / test_closes[0] - 1.0) * 100.0 if test_closes[0] else 0.0
        strat_ret = m.return_pct
        passed = bool(strat_ret > bench_ret)

        detail.windows.append(WalkForwardWindow(
            train_start=slice_bars[0].ts,
            train_end=slice_bars[train_bars - 1].ts,
            test_start=slice_bars[train_bars].ts,
            test_end=slice_bars[-1].ts,
            metrics=m,
            passed=passed,
        ))
        detail.strategy_returns.append(strat_ret)
        detail.benchmark_returns.append(round(bench_ret, 4))
        i += step_bars

    return detail


def walk_forward(
    series: OHLCVSeries,
    spec: StrategySpec,
    costs: CostModel,
    train_bars: int,
    test_bars: int,
    step_bars: int,
) -> list[WalkForwardWindow]:
    """Rolling OOS windows; each ``passed`` iff the strategy beat buy-&-hold net of costs."""
    return walk_forward_detailed(series, spec, costs, train_bars, test_bars, step_bars).windows
