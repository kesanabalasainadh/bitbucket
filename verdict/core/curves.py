"""
verdict.core.curves — equity / benchmark / drawdown helpers.

The backtester already emits these three curves on its ``BacktestResult``; this
module is the small, reusable primitive behind them (and the contract entry
``equity_drawdown``). It accepts either a ready ``BacktestResult`` (pass-through)
or a sequence of per-bar strategy returns (compounds them), so WP-2's selection
can build curves from raw walk-forward returns without re-running a backtest.
"""
from __future__ import annotations

from typing import Optional, Sequence, Union


def _compound(returns: Sequence[float]) -> list[float]:
    equity, acc = [], 1.0
    for r in returns:
        acc *= (1.0 + float(r))
        equity.append(acc)
    return equity


def _drawdown(equity: Sequence[float]) -> list[float]:
    out, peak = [], float("-inf")
    for e in equity:
        peak = max(peak, e)
        out.append(e / peak - 1.0 if peak > 0 else 0.0)
    return out


def equity_drawdown(
    data: Union[object, Sequence[float]],
    benchmark_returns: Optional[Sequence[float]] = None,
) -> tuple[list[float], list[float], list[float]]:
    """Return ``(equity, benchmark, drawdown)`` curves.

    * If ``data`` is a ``BacktestResult`` (has ``equity_curve``), pass its curves
      through unchanged.
    * Otherwise treat ``data`` as a sequence of per-bar strategy returns and
      compound them into an equity curve (starting from 1.0 after the first bar);
      ``benchmark_returns`` is compounded likewise, else the benchmark is flat.
    """
    if hasattr(data, "equity_curve"):
        return (list(data.equity_curve), list(data.benchmark_curve), list(data.drawdown_curve))

    returns = list(data)  # type: ignore[arg-type]
    equity = _compound(returns)
    if benchmark_returns is not None:
        benchmark = _compound(benchmark_returns)
    else:
        benchmark = [1.0] * len(equity)
    return equity, benchmark, _drawdown(equity)
