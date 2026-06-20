# Exit Redesign — Pre-Registered Experiment

**Date opened:** 2026-06-11 (before first variant was run)
**Hypothesis under test:** the swing system's failure is in the exits,
not the entries. Avg-win/avg-loss = 0.93× against a required 2.48×
implies winners are being closed before their thesis plays out.

**Data window:** 2021-01-01 → 2024-12-31 (FIVE walk-forward test windows)
**Holdout:** 2025-01-01 onwards is OFF-LIMITS until the redesign is
finalised. The single final-exam run against the holdout will happen
exactly once, when the redesigned rules are frozen.

**Capital:** ₹1,00,000 per window (3.33× the original ₹30k).
Reason: flat brokerage was 0.5 % of our tiny positions at ₹30k;
realistic sizing has to be measured before crediting any redesign.

**Regime gate:** ON (matches the live engine).

## Variants

The baseline is the live `config/swing_config.yaml` values at the
new ₹1L capital.

| Variant | Description                                                                                       |
|---------|---------------------------------------------------------------------------------------------------|
| **V0**  | **Baseline** at ₹1L capital, no other change.                                                     |
| **A**   | `stale_trade_days` removed (=999), `max_hold_days = 20`. Let winners run.                          |
| **B**   | Trailing stop only — no fixed target. After best ≥ entry + 1.5 ATR, trail at 1.0 ATR. `max_hold_days = 20`. |
| **C**   | Partial profit — half off at +1.5 ATR (booked separately), remainder trails at 1.5 ATR. `max_hold_days = 20`. |
| **D**   | A + tighter stops — same as A plus `sl_atr_mult = 1.0` instead of 1.5.                              |

No other parameters change. The signal generator, universe, regime
config, and gate are identical across variants. This isolates the
exit-side effect.

## Selection rule — committed before any variant is run

A variant **wins** only if BOTH of the following hold:

1. **Net-positive in at least 4 of 5 train windows.**
2. **Beats the other variants on MEDIAN window net P&L** (not best, not
   total — median, so one lucky window can't carry the rest).

If no variant satisfies both, the redesign pivots to entries — the
exits weren't the problem and the next experiment will target the
signal generator.

## Output contract

`scripts/experiment_exit_redesign.py` will emit
`experiments/2026-06-11_exit_redesign_results.md` containing:
- per-variant per-window net P&L
- per-variant gross / cost / win:loss / avg holding days
- selection-rule evaluation
- verdict

The repo also keeps `experiments/2026-06-11_exit_redesign_results.json`
for any later forensic analysis.

## Discipline

- I will not touch 2025-2026 data.
- I will not tune any variant after seeing window-by-window results.
- I will not add a variant after seeing this run's outcome.
- If no variant wins, that is the result.
