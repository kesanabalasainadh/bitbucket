# Exit-Redesign Experiment — Results

Run: **2026-06-11 02:33**
Data window: **2021-01-01** → **2024-12-31** (5 train windows). 2025+ untouched.
Capital per window: ₹100,000
Regime: ON. Universe: 26 symbols.

Pre-registration: see `experiments/2026-06-11_exit_redesign.md` (committed BEFORE this run).

## Per-variant summary

| variant | trades | net (Rs) | gross (Rs) | charges (Rs) | gross/trade | cost/trade | win:loss | avg hold (d) | windows net-positive | median window net (Rs) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 | 166 | -1,040 | +17,505 | 18,545 | +105.45 | 111.72 | 1.31x | 4.3 | 2/5 | -1,492 |
| A | 79 | +16,605 | +25,408 | 8,803 | +321.61 | 111.43 | 1.49x | 12.7 | 3/5 | +3,256 |
| B | 111 | -20,777 | -8,354 | 12,423 | -75.26 | 111.92 | 0.48x | 7.0 | 0/5 | -3,797 |
| C | 172 | -13,740 | +2,752 | 16,492 | +16.00 | 95.88 | 0.49x | 7.1 | 0/5 | -3,043 |
| D | 97 | +7,862 | +18,655 | 10,793 | +192.32 | 111.27 | 2.26x | 9.3 | 3/5 | +3,475 |

## Per-window net P&L (Rs)

| variant | 2022-07-01_to_2022-12-31 | 2023-01-01_to_2023-06-30 | 2023-07-01_to_2023-12-31 | 2024-01-01_to_2024-06-30 | 2024-07-01_to_2024-12-31 |
|---|---:|---:|---:|---:|---:|
| V0 | -1,631 | -3,450 | +4,604 | +929 | -1,492 |
| A | -345 | +3,256 | +7,334 | +7,910 | -1,551 |
| B | -1,903 | -6,605 | -3,797 | -3,006 | -5,467 |
| C | -275 | -4,791 | -3,043 | -1,142 | -4,489 |
| D | -3,099 | +3,475 | +4,373 | +7,308 | -4,196 |

## Selection-rule evaluation

**No variant satisfied Rule 1** (≥ 4 of 5 windows net-positive). Per the pre-committed plan, the redesign pivots to ENTRIES — the exits weren't the binding constraint.

## Discipline self-check

- Data window: 2021-01-01 → 2024-12-31. ✓
- Holdout enforced: every variant ran with `--holdout-from 2025-01-01` semantics. ✓
- Variant grid: pre-committed in `experiments/2026-06-11_exit_redesign.md`. ✓
- Selection rule applied exactly as written. ✓
