"""TDD for verdict.core.backtest — the no-lookahead, deterministic, cost-netted
single-asset backtester (Track-2 critical path).

The marquee test is the LOOKAHEAD PROBE: any trade that *completes* before a cut
index must be byte-identical when every bar after the cut is replaced with garbage.
If that holds, the engine provably uses no future information.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from verdict.schema import OHLCVBar, OHLCVSeries, StrategyMetrics, StrategySpec
from verdict.core import backtest as bt
from verdict.core.costs import CostModel


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _series(closes, *, timeframe="4h", symbol="BNB/USDT", highs=None, lows=None, opens=None):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(hours=4)
    bars = []
    for i, c in enumerate(closes):
        o = opens[i] if opens is not None else (closes[i - 1] if i > 0 else c)
        h = highs[i] if highs is not None else max(o, c) + 0.5
        lo = lows[i] if lows is not None else min(o, c) - 0.5
        bars.append(OHLCVBar(ts=base + i * step, open=float(o), high=float(h),
                             low=float(lo), close=float(c), volume=1000.0))
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, bars=bars)


def _spec(**over):
    base = dict(
        id="t", name="t", description="t", assets=["BNB/USDT"], timeframe="4h",
        horizon="swing", lookback=50,
        indicators=["EMA(20)", "EMA(50)", "ATR(14)"],
        entry_rules=["close > ema_20", "ema_20 > ema_50"],
        exit_rules=["max_hold=8 bars"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        position_size="risk 2% of equity per trade",
        metrics=StrategyMetrics(return_pct=0, sharpe_ratio=0, win_rate=0,
                                max_drawdown=0, risk_score=0),
    )
    base.update(over)
    return StrategySpec(**base)


def _uptrend(n=260, rate=1.004, start=100.0):
    return [start * (rate ** i) for i in range(n)]


# --------------------------------------------------------------------------- #
# Core behaviors
# --------------------------------------------------------------------------- #
def test_clean_uptrend_trend_strategy_is_profitable():
    series = _series(_uptrend())
    m = bt.backtest(series, _spec(), CostModel(gas_usd=0.0))
    assert isinstance(m, StrategyMetrics)
    assert m.num_trades >= 1
    assert m.return_pct > 0          # a trend strategy must make money in a clean uptrend


def test_fill_is_next_bar_open_not_signal_bar():
    series = _series(_uptrend())
    res = bt.backtest_detailed(series, _spec(), CostModel(gas_usd=0.0))
    assert res.trades, "expected at least one trade"
    df = series.to_dataframe()
    opens = df["open"].to_numpy()
    for tr in res.trades:
        assert tr.entry_index == tr.signal_index + 1          # signal@close[t] -> fill@open[t+1]
        assert tr.entry_price == pytest.approx(opens[tr.entry_index])


def test_determinism_two_runs_identical():
    series = _series(_uptrend())
    spec, costs = _spec(), CostModel(gas_usd=0.0)
    a = bt.backtest(series, spec, costs)
    b = bt.backtest(series, spec, costs)
    assert a.model_dump() == b.model_dump()


def test_cost_gate_rejects_thin_edge_but_allows_fat_edge():
    series = _series(_uptrend())
    costs = CostModel(fee_pct=0.0025, slippage_bps=30.0, gas_usd=0.0)
    thin = _spec(take_profit="0.1%", stop_loss="0.1%")     # reward << k * round-trip cost
    fat = _spec(take_profit="15%", stop_loss="5%")
    assert bt.backtest(series, thin, costs).num_trades == 0
    assert bt.backtest(series, fat, costs).num_trades >= 1


def test_no_lookahead_probe_future_cannot_change_the_past():
    # A deterministic, choppy series so trades actually open and close before the cut.
    import math
    closes = [100 + 18 * math.sin(i / 6.0) + 0.25 * i for i in range(220)]
    series = _series(closes)
    spec, costs = _spec(exit_rules=["max_hold=6 bars"]), CostModel(gas_usd=0.0)
    res1 = bt.backtest_detailed(series, spec, costs)

    cut = 140
    # Replace every bar at/after the cut with garbage (still valid OHLC).
    poisoned = list(closes[:cut]) + [999.0 - (i % 7) for i in range(cut, len(closes))]
    series2 = _series(poisoned)
    res2 = bt.backtest_detailed(series2, spec, costs)

    def completed_before(res):
        return [(t.signal_index, t.entry_index, t.exit_index,
                 round(t.entry_price, 9), round(t.exit_price, 9), t.reason)
                for t in res.trades if t.exit_index < cut]

    assert completed_before(res1), "probe needs at least one trade completed before the cut"
    assert completed_before(res1) == completed_before(res2)


def test_curves_are_normalized_and_aligned():
    series = _series(_uptrend())
    res = bt.backtest_detailed(series, _spec(), CostModel(gas_usd=0.0))
    eq, bench, dd = res.equity_curve, res.benchmark_curve, res.drawdown_curve
    assert len(eq) == len(bench) == len(dd) > 0
    assert eq[0] == pytest.approx(1.0)
    assert bench[0] == pytest.approx(1.0)
    assert all(d <= 1e-9 for d in dd)         # drawdown is <= 0
    assert max(dd) == pytest.approx(0.0, abs=1e-9)


def test_flat_market_no_signal_means_no_trades_and_zero_return():
    series = _series([100.0] * 200)            # dead flat: entry rules never all-true
    m = bt.backtest(series, _spec(), CostModel(gas_usd=0.0))
    assert m.num_trades == 0
    assert m.return_pct == pytest.approx(0.0)


def test_metrics_drawdown_is_positive_percent():
    # down-then-up so there is a real drawdown to report
    import math
    closes = [100 - 0.2 * i + 5 * math.sin(i / 5.0) for i in range(120)] + \
             [80 + 0.5 * i for i in range(120)]
    series = _series(closes)
    m = bt.backtest(series, _spec(), CostModel(gas_usd=0.0))
    assert m.max_drawdown >= 0.0               # reported as a positive % magnitude


def test_demo_main_prints_metrics_json(capsys):
    rc = bt.main(["--demo"])
    out = capsys.readouterr().out
    assert rc == 0
    import json
    payload = json.loads(out.strip().splitlines()[-1])
    assert "return_pct" in payload and "sharpe_ratio" in payload and "num_trades" in payload
