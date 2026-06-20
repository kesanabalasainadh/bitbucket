"""TDD for verdict.core.curves — equity / benchmark / drawdown helpers."""
from __future__ import annotations

import pytest

from verdict.core import curves


def test_equity_drawdown_from_returns_compounds():
    eq, bench, dd = curves.equity_drawdown([0.10, 0.0, -0.05])
    assert eq[0] == pytest.approx(1.10)
    assert eq[1] == pytest.approx(1.10)
    assert eq[2] == pytest.approx(1.10 * 0.95)
    # drawdown is peak-relative and <= 0
    assert dd[0] == pytest.approx(0.0)
    assert dd[2] == pytest.approx(1.045 / 1.10 - 1.0)
    assert len(eq) == len(bench) == len(dd) == 3


def test_equity_drawdown_uses_benchmark_returns_when_given():
    eq, bench, dd = curves.equity_drawdown([0.0, 0.0], benchmark_returns=[0.2, 0.1])
    assert bench[0] == pytest.approx(1.2)
    assert bench[1] == pytest.approx(1.2 * 1.1)


def test_equity_drawdown_passthrough_for_backtest_result():
    class _R:
        equity_curve = [1.0, 1.1, 1.05]
        benchmark_curve = [1.0, 1.02, 1.04]
        drawdown_curve = [0.0, 0.0, -0.045]

    eq, bench, dd = curves.equity_drawdown(_R())
    assert eq == [1.0, 1.1, 1.05]
    assert bench == [1.0, 1.02, 1.04]
    assert dd == [0.0, 0.0, -0.045]
