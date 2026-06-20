"""
verdict.core.backtest — the no-lookahead, deterministic, cost-netted backtester.

This is the Track-2 critical path: it turns a deterministic ``StrategySpec`` (rules
in verdict.core.rules' grammar) into honest ``StrategyMetrics`` + curves, with three
non-negotiable guarantees a judge can verify:

  1. NO LOOKAHEAD. A rule is evaluated on bar t's CLOSE; the order fills at the
     t+1 OPEN. Stop/target are resting intrabar orders set at entry (price levels,
     not future bars). Every indicator column is strictly causal, so a decision at
     bar t is independent of every bar > t. (See the lookahead-probe test.)

  2. DETERMINISM. No RNG, no clock, no network. Identical inputs -> identical
     StrategyMetrics, byte for byte.

  3. HONEST COSTS. Every round trip pays the CostModel's fee + slippage (+ gas).
     Friction is modeled ONCE, in the cost model — fills are at the raw open, so
     slippage is never double-counted. A pre-trade gate refuses trades whose
     expected move can't clear round-trip cost ``k`` times over.

Crypto is 24/7: no weekday/holiday gates; the timeframe (1h/4h/1d/...) is a
parameter and drives Sharpe annualization (bars-per-year).

    backtest(series, spec, costs)          -> StrategyMetrics
    backtest_detailed(series, spec, costs) -> BacktestResult(metrics, equity_curve,
                                              benchmark_curve, drawdown_curve, trades)
    python -m verdict.core.backtest --demo -> prints StrategyMetrics JSON
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from verdict.schema import OHLCVBar, OHLCVSeries, StrategyMetrics, StrategySpec
from verdict.core import rules
from verdict.core.costs import CostModel, PANCAKESWAP_V2

STARTING_CAPITAL = 10_000.0

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}
_SECONDS_PER_YEAR = 365.0 * 86400.0
_RISK_RE = re.compile(r"risk\s*([0-9.]+)\s*%")


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Trade:
    signal_index: int          # bar whose CLOSE produced the signal
    entry_index: int           # bar whose OPEN we filled at (== signal_index + 1)
    exit_index: int
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    units: float
    notional: float
    gross_pnl: float
    cost: float
    net_pnl: float
    return_pct: float           # net P&L as % of entry notional
    reason: str                 # stop | target | rule_exit | max_hold | end_of_data


@dataclass
class BacktestResult:
    metrics: StrategyMetrics
    equity_curve: list[float] = field(default_factory=list)      # normalized, starts 1.0
    benchmark_curve: list[float] = field(default_factory=list)   # buy & hold, starts 1.0
    drawdown_curve: list[float] = field(default_factory=list)    # <= 0, fraction
    trades: list[Trade] = field(default_factory=list)
    timestamps: list[datetime] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def periods_per_year(timeframe: str) -> float:
    tf = (timeframe or "1d").lower().strip()
    secs = _TF_SECONDS.get(tf)
    if secs is None:
        m = re.match(r"^(\d+)\s*([mhdw])$", tf)
        if m:
            unit = {"m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]
            secs = int(m.group(1)) * unit
    return _SECONDS_PER_YEAR / (secs or 86400)


def _risk_fraction(spec: StrategySpec) -> float:
    m = _RISK_RE.search((spec.position_size or "").lower())
    return float(m.group(1)) / 100.0 if m else 0.02


def _warmup_bars(spec: StrategySpec, n: int) -> int:
    text = " ".join(
        list(spec.entry_rules) + list(spec.exit_rules)
        + [spec.stop_loss or "", spec.take_profit or ""] + list(spec.indicators)
    ).lower()
    periods = [int(x) for x in re.findall(
        r"(?:ema_|sma_|rsi_|atr_|adx_|vol_sma_|donchian_high_|donchian_low_)(\d+)", text)]
    periods += [int(x) for x in re.findall(r"atr\((\d+)\)", text)]
    if "macd" in text:
        periods.append(26)
    if "bb_" in text or "bollinger" in text:
        periods.append(20)
    w = (max(periods) + 2) if periods else 5
    return max(1, min(w, n - 2))


def _zero_metrics() -> StrategyMetrics:
    return StrategyMetrics(return_pct=0.0, sharpe_ratio=0.0, win_rate=0.0,
                           max_drawdown=0.0, risk_score=0.0)


def _level_price(df, level, entry: float, sig: int, sign: int) -> Optional[float]:
    """Price of a stop (sign=-1) / target (sign=+1) level from entry. None if N/A."""
    if level is None:
        return None
    if level.kind == "atr":
        atr = rules.operand_value(df, f"atr_{level.n}", sig)
        if math.isnan(atr):
            return None
        return entry + sign * level.k * atr
    return entry * (1.0 + sign * level.k)        # pct


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def backtest_detailed(
    series: OHLCVSeries,
    spec: StrategySpec,
    costs: CostModel,
    *,
    trade_start: Optional[int] = None,
    gate_k: float = 3.0,
    max_frac: float = 1.0,
) -> BacktestResult:
    df = rules.prepare(series.to_dataframe())
    n = len(df)
    if n < 3:
        return BacktestResult(metrics=_zero_metrics())

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    ts_index = list(df.index)

    entry_rules = list(spec.entry_rules)
    exit_sig_rules = rules.grammar_exit_rules(spec.exit_rules)
    max_hold = rules.parse_max_hold(spec.exit_rules)
    stop_level = rules.parse_exit_level(spec.stop_loss)
    target_level = rules.parse_exit_level(spec.take_profit)
    risk_pct = _risk_fraction(spec)
    ppy = periods_per_year(spec.timeframe or series.timeframe)

    if trade_start is None:
        trade_start = _warmup_bars(spec, n)
    trade_start = max(1, min(int(trade_start), n - 1))

    cash = STARTING_CAPITAL
    units = 0.0
    pos: Optional[dict] = None
    pending_entry: Optional[int] = None      # signal_index awaiting a t+1 open fill
    pending_exit: Optional[str] = None       # reason awaiting a t+1 open fill
    trades: list[Trade] = []
    equity_curve: list[float] = []
    bench_curve: list[float] = []
    dd_curve: list[float] = []
    active_ts: list[datetime] = []
    bench_anchor = float(closes[trade_start])
    peak = STARTING_CAPITAL
    in_pos_bars = 0

    def _close(exit_index: int, exit_price: float, reason: str) -> None:
        nonlocal cash, units, pos
        assert pos is not None
        notional = pos["notional"]
        rt_cost = costs.round_trip_cost(notional)
        gross = units * (exit_price - pos["entry_price"])
        cash += units * exit_price - costs.leg_cost(notional)     # exit leg
        net = gross - rt_cost
        trades.append(Trade(
            signal_index=pos["signal_index"], entry_index=pos["entry_index"],
            exit_index=exit_index, entry_ts=ts_index[pos["entry_index"]],
            exit_ts=ts_index[exit_index], entry_price=pos["entry_price"],
            exit_price=float(exit_price), units=units, notional=notional,
            gross_pnl=gross, cost=rt_cost, net_pnl=net,
            return_pct=(net / notional * 100.0) if notional else 0.0, reason=reason,
        ))
        units = 0.0
        pos = None

    for t in range(trade_start, n):
        # (A) resolve a fill scheduled at the previous bar's close, executed at open[t]
        if pending_exit is not None and pos is not None:
            _close(t, float(opens[t]), pending_exit)
            pending_exit = None
        elif pending_entry is not None and pos is None:
            sig = pending_entry
            entry = float(opens[t])
            stop_price = _level_price(df, stop_level, entry, sig, -1)
            target_price = _level_price(df, target_level, entry, sig, +1)
            stop_dist = (entry - stop_price) if stop_price is not None else None
            if stop_dist is not None and stop_dist > 0:
                qty = (risk_pct * cash) / stop_dist
            else:
                qty = (max_frac * cash) / entry
            notional = qty * entry
            if notional > max_frac * cash:
                notional = max_frac * cash
                qty = notional / entry
            if target_price is not None:
                reward = qty * (target_price - entry)
            elif stop_dist is not None and stop_dist > 0:
                reward = qty * stop_dist
            else:
                reward = qty * entry * 0.05
            if notional > 0 and costs.clears_costs(reward, notional, k=gate_k):
                cash -= notional + costs.leg_cost(notional)        # entry leg
                units = qty
                pos = dict(entry_index=t, signal_index=sig, entry_price=entry,
                           notional=notional, stop=stop_price, target=target_price)
            pending_entry = None

        # (B) intrabar resting orders on bar t — STOP checked before TARGET
        if pos is not None:
            if pos["stop"] is not None and lows[t] <= pos["stop"]:
                _close(t, min(pos["stop"], float(opens[t])), "stop")
            elif pos["target"] is not None and highs[t] >= pos["target"]:
                _close(t, max(pos["target"], float(opens[t])), "target")

        # (C) rule / max_hold exits decided at close[t] -> fill at t+1 open
        if pos is not None and pending_exit is None:
            held = t - pos["entry_index"]
            hit_max = max_hold is not None and held >= max_hold
            rule_hit = any(rules.evaluate_rule(df, t, r) for r in exit_sig_rules)
            if hit_max or rule_hit:
                reason = "max_hold" if hit_max else "rule_exit"
                if t + 1 < n:
                    pending_exit = reason
                else:
                    _close(t, float(closes[t]), reason)

        # (D) entries decided at close[t] -> fill at t+1 open
        if pos is None and pending_entry is None and pending_exit is None:
            if t + 1 < n and rules.rules_all(df, t, entry_rules):
                pending_entry = t

        # force-close anything still open on the final bar
        if pos is not None and t == n - 1:
            _close(t, float(closes[t]), "end_of_data")

        # (E) mark to market at close[t]
        eq = cash + units * float(closes[t])
        if units > 0:
            in_pos_bars += 1
        equity_curve.append(eq / STARTING_CAPITAL)
        bench_curve.append(float(closes[t]) / bench_anchor)
        peak = max(peak, eq)
        dd_curve.append(eq / peak - 1.0)
        active_ts.append(ts_index[t])

    metrics = _metrics_from_curves(equity_curve, dd_curve, trades, ppy, in_pos_bars,
                                   risk_pct, stop_level, target_level)
    return BacktestResult(metrics=metrics, equity_curve=equity_curve,
                          benchmark_curve=bench_curve, drawdown_curve=dd_curve,
                          trades=trades, timestamps=active_ts)


def _metrics_from_curves(equity, dd_curve, trades, ppy, in_pos_bars,
                         risk_pct, stop_level, target_level) -> StrategyMetrics:
    if len(equity) < 2:
        return _zero_metrics()
    returns = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    std = math.sqrt(var)
    sharpe = (mean_r / std) * math.sqrt(ppy) if std > 1e-12 else 0.0
    downside = [r for r in returns if r < 0]
    dstd = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    sortino = (mean_r / dstd) * math.sqrt(ppy) if dstd > 1e-12 else 0.0

    return_pct = (equity[-1] / equity[0] - 1.0) * 100.0
    max_dd = -min(dd_curve) * 100.0 if dd_curve else 0.0

    nets = [t.net_pnl for t in trades]
    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p < 0]
    win_rate = (len(wins) / len(nets)) if nets else 0.0
    gp, gl = sum(wins), abs(sum(losses))
    profit_factor = round(gp / gl, 4) if gl > 0 else (999.0 if gp > 0 else 0.0)

    sl_echo = (stop_level.k if stop_level else None)
    tp_echo = (target_level.k if target_level else None)
    return StrategyMetrics(
        return_pct=round(return_pct, 4),
        sharpe_ratio=round(sharpe, 4),
        win_rate=round(win_rate, 4),
        max_drawdown=round(max_dd, 4),
        risk_score=0.0,                       # WP-2's select.py fills the composite
        num_trades=len(trades),
        sortino_ratio=round(sortino, 4),
        profit_factor=profit_factor,
        exposure_pct=round(100.0 * in_pos_bars / len(equity), 4),
        position_size=round(risk_pct, 6),
        stop_loss=sl_echo,
        take_profit=tp_echo,
    )


def backtest(series: OHLCVSeries, spec: StrategySpec, costs: CostModel) -> StrategyMetrics:
    """Backtest ``spec`` on ``series``; return StrategyMetrics (no-lookahead, net of costs)."""
    return backtest_detailed(series, spec, costs).metrics


# --------------------------------------------------------------------------- #
# Demo / CLI
# --------------------------------------------------------------------------- #
def _demo_spec(symbol: str = "BNB/USDT", timeframe: str = "4h") -> StrategySpec:
    return StrategySpec(
        id="demo-momentum", name="Demo Momentum Pullback",
        description="EMA-stack trend + MACD-momentum entry, ATR exits (CLI demo).",
        assets=[symbol], timeframe=timeframe, horizon="swing (2-10 bars)", lookback=120,
        indicators=["EMA(20)", "EMA(50)", "EMA(100)", "MACD", "ATR(14)", "RSI(14)"],
        entry_rules=["close > ema_100", "ema_20 > ema_50", "macd_hist rising"],
        exit_rules=["max_hold=10 bars", "rsi_14 > 78"],
        stop_loss="2.0 * ATR(14)", take_profit="4.0 * ATR(14)",
        position_size="risk 2% of equity per trade",
        cost_model=PANCAKESWAP_V2.label, metrics=_zero_metrics(),
    )


def _synthetic_series(symbol: str, timeframe: str, n: int = 420) -> OHLCVSeries:
    """Deterministic (RNG-free) trending series for the offline/no-network demo."""
    secs = _TF_SECONDS.get(timeframe, 14400)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = timedelta(seconds=secs)
    closes = [100.0 * (1.0035 ** i) + 6.0 * math.sin(i / 7.0) for i in range(n)]
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) + 0.6
        lo = min(o, c) - 0.6
        bars.append(OHLCVBar(ts=base + i * step, open=o, high=h, low=lo, close=c, volume=1000.0))
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, source="synthetic", bars=bars)


def _demo_series(symbol: str, timeframe: str) -> OHLCVSeries:
    """Prefer real committed candles (offline fixture); fall back to synthetic."""
    try:
        from verdict.core.data import load_ohlcv
        series = load_ohlcv(symbol, timeframe)
        if len(series.bars) >= 60:
            return series
    except Exception:
        pass
    return _synthetic_series(symbol, timeframe)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="VERDICT backtester demo (offline-first).")
    parser.add_argument("--demo", action="store_true", help="run the offline demo")
    parser.add_argument("--asset", default="BNB/USDT")
    parser.add_argument("--tf", default="4h")
    args = parser.parse_args(argv)

    series = _demo_series(args.asset, args.tf)
    spec = _demo_spec(args.asset, args.tf)
    m = backtest(series, spec, PANCAKESWAP_V2)
    print(f"# VERDICT backtest demo — {args.asset} {args.tf} "
          f"({series.source}, {len(series.bars)} bars)", file=sys.stderr)
    print(json.dumps(m.model_dump(), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
