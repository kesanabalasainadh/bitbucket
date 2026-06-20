# Entry-Redesign Experiment — Results

Run: **2026-06-11 02:46**
Data window: **2021-01-01** → **2024-12-31** (5 train windows). 2025+ untouched.
Capital per window: ₹100,000. Regime: ON. Universe: 26 symbols.
Pre-registration: see `experiments/2026-06-11_entry_redesign.md` (committed 21d8b87, before any code or run).

**Honest summary:** No cell passed all three pre-committed criteria. The current EMA-pullback signal family — and the two breakout variants — cannot generate a swing system that beats a 7 % FD net of costs on this universe. The redesign loop stops here per the pre-registration.

## All 10 cells — full diagnosis

| cell | trades | net (₹) | gross (₹) | charges (₹) | gross/trade | cost/trade | win:loss | win rate | avg hold (d) | +windows/5 | median win net (₹) | 2024-H2 (₹) | trades/window |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E0/A | 71 | +11,982 | +19,848 | 7,866 | +279.6 | 110.8 | 1.12× | 56.3% | 14.3 | 4/5 | +2,128 | +1,290 | 14.2 |
| E0/D | 98 | -3,299 | +7,560 | 10,859 | +77.1 | 110.8 | 1.78× | 33.7% | 8.9 | 3/5 | +111 | -3,979 | 19.6 |
| E1/A | 67 | +11,725 | +19,159 | 7,434 | +285.9 | 111.0 | 1.16× | 56.7% | 14.8 | 4/5 | +1,290 | +1,290 | 13.4 |
| E1/D | 94 | +1,754 | +12,191 | 10,437 | +129.7 | 111.0 | 1.90× | 36.2% | 9.4 | 3/5 | +111 | -3,979 | 18.8 |
| E2/A | 69 | +1,877 | +9,522 | 7,645 | +138.0 | 110.8 | 1.22× | 47.8% | 13.4 | 4/5 | +928 | -7,609 | 13.8 |
| E2/D | 85 | +4,469 | +13,895 | 9,426 | +163.5 | 110.9 | 2.25× | 35.3% | 9.5 | 4/5 | +1,304 | -2,908 | 17.0 |
| E3/A | 61 | -12,659 | -5,924 | 6,735 | -97.1 | 110.4 | 0.91× | 39.3% | 13.7 | 1/5 | -2,549 | -4,854 | 12.2 |
| E3/D | 81 | -13,755 | -4,826 | 8,929 | -59.6 | 110.2 | 2.13× | 22.2% | 7.8 | 1/5 | -3,529 | -4,454 | 16.2 |
| E4/A | 60 | -13,146 | -6,483 | 6,663 | -108.1 | 111.1 | 0.93× | 36.7% | 12.9 | 1/5 | -1,407 | -6,673 | 12.0 |
| E4/D | 69 | -13,137 | -5,481 | 7,656 | -79.4 | 110.9 | 1.96× | 20.3% | 8.7 | 1/5 | -2,970 | -4,020 | 13.8 |

## Three-criterion pass/fail

| cell | (a) ≥4/5 positive | (b) median ≥ ₹3,500 | (c) 2024-H2 ≥ −₹500 | hygiene ≥ 8 trades/win | passes all? |
|---|---|---|---|---|---|
| E0/A | ✓ (4/5) | ✗ (₹+2,128) | ✓ (₹+1,290) | ✓ (14.2) | ✗ |
| E0/D | ✗ (3/5) | ✗ (₹+111) | ✗ (₹-3,979) | ✓ (19.6) | ✗ |
| E1/A | ✓ (4/5) | ✗ (₹+1,290) | ✓ (₹+1,290) | ✓ (13.4) | ✗ |
| E1/D | ✗ (3/5) | ✗ (₹+111) | ✗ (₹-3,979) | ✓ (18.8) | ✗ |
| E2/A | ✓ (4/5) | ✗ (₹+928) | ✗ (₹-7,609) | ✓ (13.8) | ✗ |
| E2/D | ✓ (4/5) | ✗ (₹+1,304) | ✗ (₹-2,908) | ✓ (17.0) | ✗ |
| E3/A | ✗ (1/5) | ✗ (₹-2,549) | ✗ (₹-4,854) | ✓ (12.2) | ✗ |
| E3/D | ✗ (1/5) | ✗ (₹-3,529) | ✗ (₹-4,454) | ✓ (16.2) | ✗ |
| E4/A | ✗ (1/5) | ✗ (₹-1,407) | ✗ (₹-6,673) | ✓ (12.0) | ✗ |
| E4/D | ✗ (1/5) | ✗ (₹-2,970) | ✗ (₹-4,020) | ✓ (13.8) | ✗ |

## Per-window net P&L (₹)

| cell | 2022-07-01_to_2022-12-31 | 2023-01-01_to_2023-06-30 | 2023-07-01_to_2023-12-31 | 2024-01-01_to_2024-06-30 | 2024-07-01_to_2024-12-31 |
|---|---:|---:|---:|---:|---:|
| E0/A | -2,674 | +2,128 | +6,247 | +4,991 | +1,290 |
| E0/D | -1,733 | +755 | +1,546 | +111 | -3,979 |
| E1/A | -629 | +907 | +5,166 | +4,991 | +1,290 |
| E1/D | -971 | +1,292 | +5,300 | +111 | -3,979 |
| E2/A | +140 | +928 | +4,623 | +3,796 | -7,609 |
| E2/D | +443 | +1,304 | +3,111 | +2,520 | -2,908 |
| E3/A | -2,549 | -5,883 | +848 | -223 | -4,854 |
| E3/D | -2,480 | -5,851 | +2,557 | -3,529 | -4,454 |
| E4/A | -1,407 | -5,729 | +1,380 | -718 | -6,673 |
| E4/D | -1,397 | -6,450 | +1,700 | -2,970 | -4,020 |

## Filter-rejection counts

How many candidate entries each new filter refused, summed across all windows.

| cell | rejection counters |
|---|---|
| E0/A | _(no filter-specific rejections — E0 / baseline)_ |
| E0/D | _(no filter-specific rejections — E0 / baseline)_ |
| E1/A | `E1_trend_filter=267` |
| E1/D | `E1_trend_filter=283` |
| E2/A | `E1_trend_filter=285`, `E2_relative_strength=92` |
| E2/D | `E1_trend_filter=290`, `E2_relative_strength=120` |
| E3/A | `E3_day_of_week=10634`, `E3_no_breakout_close=6315`, `E3_volume_below=250` |
| E3/D | `E3_day_of_week=14750`, `E3_no_breakout_close=8282`, `E3_volume_below=317` |
| E4/A | `E3_day_of_week=14008`, `E3_no_breakout_close=8304`, `E3_volume_below=351`, `E4_trend_filter=156` |
| E4/D | `E3_day_of_week=16531`, `E3_no_breakout_close=9857`, `E3_volume_below=413`, `E4_trend_filter=170` |

## Selection-rule evaluation

**No cell passed all three criteria.** Per the pre-registered plan, the verdict is: this strategy family cannot beat an FD after costs. The redesign loop **stops**. No E5 is proposed; no criterion is softened. Await direction.

## Discipline self-check

- Data window: 2021-01-01 → 2024-12-31. ✓
- Holdout enforced: every cell skips windows whose test period starts on/after 2025-01-01. ✓
- Grid: 5 entries × 2 exits, pre-committed in `experiments/2026-06-11_entry_redesign.md` (commit 21d8b87). ✓
- Selection rule applied exactly as written. ✓
- Holdout 2025+ untouched. ✓
