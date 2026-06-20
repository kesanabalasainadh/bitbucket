# Entry Redesign — Pre-Registered Experiment

**Date opened:** 2026-06-11 (before any variant was run)
**Hypothesis under test:** the swing system's failure is in the entries
— the current 6-condition EMA-pullback signal does not produce setups
strong enough to clear realistic costs even under the better exit
configurations from the prior experiment.

**Data window:** 2021-01-01 → 2024-12-31 (FIVE walk-forward test windows).
**Holdout:** 2025-01-01 onwards is OFF-LIMITS. Final-exam run happens
exactly once, after a winner is approved.

**Capital:** ₹1,00,000 per window. **Regime gate:** ON. Universe and
risk parameters frozen as-is.

**Exits are FIXED carries from the closed exit experiment (commit
2de09b9)** — no exit tuning in this experiment:
- **Exit-A**: `stale_trade_days = 0` (disabled), `max_hold_days = 20`.
- **Exit-D**: Exit-A + `sl_atr_mult = 1.0` (tighter stops).

## The Grid — 10 cells

Five entry variants × two exits.

| Entry | Description |
|---|---|
| **E0** | Current 6-condition EMA-pullback signal generator (baseline). |
| **E1** | E0 plus stock-level trend filter: `close > SMA(close, 200)` AND `SMA(close, 50) > SMA(close, 200)`. |
| **E2** | E1 plus relative strength: stock's 63-day return at T-1 close > Nifty 50's 63-day return at T-1 close. |
| **E3** | Breakout replaces EMA pullback: `close[T] > max(high[T-20 .. T-1])` AND `volume[T] >= 1.5 × mean(volume[T-20 .. T-1])`. Signal on T close, fill at T+1 open. |
| **E4** | E3 plus E1's stock-trend filter (breakout only in established uptrends). |

## No-lookahead audit anchors

Every new indicator is computed from bars **up to and including the
signal bar** (day T close), never beyond. The actual fill is always
T+1 open. Specific anchors:

| Indicator | Computed from | Date span |
|---|---|---|
| E1 trend (200d SMA, 50d SMA) | `close` column of `hist_df` | up to and including T close |
| E2 stock 63d return | `close[T-1] / close[T-1-63] - 1` (strict T-1, **excludes T**) | T-1 only |
| E2 Nifty 63d return | `nifty_series.loc[<T]` last value / 63 bars earlier | strict T-1 |
| E3 prior 20-day high | `max(high[T-20 .. T-1])` (**excludes T**) | T-1 and earlier |
| E3 20-day avg volume | `mean(volume[T-20 .. T-1])` (**excludes T**) | T-1 and earlier |
| E3 current bar volume | `volume[T]` | T only |
| E4 (= E3 ∩ E1 trend) | as above | as above |

The volume comparison in E3/E4 uses today's volume vs the trailing
average from the PRIOR 20 days, which is the standard breakout
definition and not a lookahead.

## Selection Rule — committed BEFORE running

A cell **wins** only if ALL THREE criteria pass:

1. **Net-positive in ≥ 4 of 5 train windows.**
2. **Median window net ≥ ₹3,500** (FD-equivalent: ~7%/yr on ₹1L per
   6-month window).
3. **2024-H2 window net ≥ −₹500** (positive or near-flat in the
   universal-failure window from prior runs).

Statistical hygiene: cells averaging **< 8 trades per window** are
labelled **"insufficient sample"** and cannot be declared winners
regardless of P&L numbers. Filters are expected to cut frequency;
that is acceptable.

## What happens after the grid runs

- **If no cell passes all three:** report plainly. Verdict will read
  "this strategy family cannot beat an FD after costs" and the
  redesign loop **stops**. No E5 will be proposed. No softening of
  criteria (a), (b), or (c). Await direction.
- **If exactly one cell passes:** report it and the runners-up.
  Await direction for the holdout run.
- **If multiple cells pass:** rank by **median window net** (not best,
  not total). Report the top cell + runners-up. Await direction.

## Report contract

Per cell (all 10):

    trades | net | gross | charges | gross/trade | cost/trade |
    win:loss | win rate | avg hold (d) | +windows/5 |
    median window net | 2024-H2 net | trades/window

Plus:

- Three-criterion pass/fail table for all 10 cells.
- Per-group net for the top cell only.
- Filter-rejection counts (how many signals E1/E2/E3 conditions
  refused) so the filters' actual behaviour is visible.
- One-paragraph honest summary. If results are bad, the first
  sentence says so.

## Discipline

- I will not touch 2025-2026 data.
- I will not retro-add a variant after seeing this run's outcome.
- I will not retune any variant after seeing window-by-window results.
- I will not adjust criterion (a), (b), or (c) post-hoc.
- The pre-registration is the contract.
