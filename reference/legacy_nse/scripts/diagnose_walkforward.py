#!/usr/bin/env python3
"""
One-page walk-forward diagnosis — no new backtests.

Reads the JSON emitted by ``scripts/run_walkforward.py`` and answers:
  (1) Per window: gross vs charges, ON vs OFF
  (2) Skip-counter activity — was the min_profit_cost_multiple gate
      actually doing anything?
  (3) Per-group P&L summed across windows — is any group profitable
      standalone?
  (4) Avg win Rs vs avg loss Rs to characterise the trade profile.

Honest about what the existing JSON cannot answer (Q1, Q4 require
fields that were not persisted in the per_window dict).  Suggests a
one-line capture upgrade and a single re-run to complete the picture.

Usage:
    python scripts/diagnose_walkforward.py
    python scripts/diagnose_walkforward.py reports/walkforward_2026-06-11-0209.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _latest_report(report_dir: Path) -> Path:
    cands = sorted(report_dir.glob("walkforward_*.json"))
    if not cands:
        raise SystemExit(f"no walkforward_*.json in {report_dir}")
    return cands[-1]


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Q1 — per-window net + ON vs OFF; flag missing gross / charges fields.
# ---------------------------------------------------------------------------

def per_window_table(report: Dict[str, Any]) -> Tuple[str, bool]:
    """Return (markdown, has_gross_breakdown)."""
    rows = report.get("per_window", [])
    by_window: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        by_window.setdefault(r["window"], {})[r["mode"]] = r

    has_gross = any("gross_pnl" in r for r in rows)

    if has_gross:
        lines = ["| window | trades ON | gross ON (Rs) | charges ON (Rs) | net ON (Rs) | net OFF (Rs) | Δ ON-OFF |",
                 "|---|---:|---:|---:|---:|---:|---:|"]
    else:
        lines = ["| window | trades ON | net ON (Rs) | net OFF (Rs) | Δ ON-OFF | win% ON | win% OFF |",
                 "|---|---:|---:|---:|---:|---:|---:|"]
    sum_on_net = 0.0
    sum_off_net = 0.0
    sum_on_trades = 0
    sum_on_gross = 0.0
    sum_on_charges = 0.0
    for w in sorted(by_window):
        on = by_window[w].get("regime_on", {})
        off = by_window[w].get("regime_off", {})
        net_on = on.get("net_pnl", 0.0)
        net_off = off.get("net_pnl", 0.0)
        delta = net_on - net_off
        sum_on_net += net_on
        sum_off_net += net_off
        sum_on_trades += on.get("trades", 0)
        if has_gross:
            gross_on = on.get("gross_pnl", 0.0)
            charges_on = on.get("total_charges", 0.0)
            sum_on_gross += gross_on
            sum_on_charges += charges_on
            lines.append(
                f"| {w} | {on.get('trades', 0)} | "
                f"{gross_on:+,.0f} | {charges_on:,.0f} | "
                f"{net_on:+,.0f} | {net_off:+,.0f} | {delta:+,.0f} |"
            )
        else:
            lines.append(
                f"| {w} | {on.get('trades', 0)} | "
                f"{net_on:+,.0f} | {net_off:+,.0f} | "
                f"{delta:+,.0f} | "
                f"{on.get('win_rate', 0)*100:.1f}% | "
                f"{off.get('win_rate', 0)*100:.1f}% |"
            )
    if has_gross:
        lines.append(
            f"| **TOTAL** | **{sum_on_trades}** | "
            f"**{sum_on_gross:+,.0f}** | **{sum_on_charges:,.0f}** | "
            f"**{sum_on_net:+,.0f}** | **{sum_off_net:+,.0f}** | "
            f"**{sum_on_net - sum_off_net:+,.0f}** |"
        )
    else:
        lines.append(
            f"| **TOTAL** | **{sum_on_trades}** | "
            f"**{sum_on_net:+,.0f}** | **{sum_off_net:+,.0f}** | "
            f"**{sum_on_net - sum_off_net:+,.0f}** | — | — |"
        )
    return "\n".join(lines), has_gross


def cost_eaten_verdict(report: Dict[str, Any]) -> Optional[str]:
    """Cleanest single answer using the operator's pre-stated verdict bands:

      gross / trade > Rs 150 (~2x costs) → genuine edge being cost-eaten;
                                            fix is structural (fewer,
                                            bigger, longer trades).
      gross / trade Rs 0 - 150           → faint edge, can't pay rent;
                                            signal needs strengthening
                                            AND cost structure helps.
      gross / trade < 0                   → signal is anti-predictive or
                                            noise; full strategy redesign.

    Only available when gross_pnl/total_charges are in the JSON."""
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    if not rows or "gross_pnl" not in rows[0]:
        return None
    g = sum(r.get("gross_pnl", 0.0) for r in rows)
    c = sum(r.get("total_charges", 0.0) for r in rows)
    n = g - c
    total_trades = sum(r["trades"] for r in rows) or 1
    gross_per_trade = g / total_trades
    cost_per_trade = c / total_trades

    if gross_per_trade > 150.0:
        band = ("**GENUINE EDGE — COST-EATEN.** "
                "Gross / trade Rs {gpt:+,.0f} is comfortably above 2x "
                "per-trade cost (Rs {cpt:,.0f}). The strategy works in "
                "principle; the cost structure is what's killing it. "
                "Best-case verdict.")
    elif gross_per_trade > 0:
        band = ("**FAINT EDGE — CAN'T PAY RENT.** "
                "Gross / trade Rs {gpt:+,.0f} is positive but smaller "
                "than per-trade cost (Rs {cpt:,.0f}). Signal is real "
                "but too weak to clear realistic costs. Fix needs BOTH "
                "a stronger signal AND lower costs (fewer trades). "
                "Likely-case verdict.")
    else:
        band = ("**ANTI-PREDICTIVE / NOISE.** "
                "Gross / trade Rs {gpt:+,.0f} is NEGATIVE. Even at zero "
                "transaction cost the strategy would lose. The EMA + "
                "MACD + RSI rules have no edge on this universe over "
                "this period. Full strategy redesign required.")

    return (
        f"### Verdict\n\n"
        f"{band.format(gpt=gross_per_trade, cpt=cost_per_trade)}\n\n"
        f"| metric | value |\n"
        f"|---|---:|\n"
        f"| total gross | Rs {g:+,.0f} |\n"
        f"| total charges | Rs {c:,.0f} |\n"
        f"| total net | Rs {n:+,.0f} |\n"
        f"| trades | {total_trades} |\n"
        f"| gross / trade | **Rs {gross_per_trade:+,.2f}** |\n"
        f"| cost / trade | Rs {cost_per_trade:,.2f} |\n"
        f"| gross / cost ratio | {gross_per_trade / cost_per_trade:.2f}x |"
    )


def win_loss_table(report: Dict[str, Any]) -> Optional[str]:
    """Per-window win/loss table + your asymmetry threshold call:
    a 27 %-win-rate trend-follower needs avg-win >= ~3x avg-loss just
    to break even gross.
    """
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    if not rows or "avg_win" not in rows[0]:
        return None
    lines = [
        "| window | trades | wins | losses | avg win (Rs) | avg loss (Rs) | win:loss | avg hold (d) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    weighted_ratio_num = 0.0
    weighted_ratio_den = 0.0
    for r in sorted(rows, key=lambda x: x["window"]):
        wr = r.get("win_rate", 0.0)
        trades = r.get("trades", 0)
        wins = int(round(wr * trades))
        losses = trades - wins
        aw = r.get("avg_win", 0.0)
        al = r.get("avg_loss", 0.0)
        ratio = abs(aw / al) if al else float("inf")
        weighted_ratio_num += ratio * trades
        weighted_ratio_den += trades
        lines.append(
            f"| {r['window']} | {trades} | {wins} | {losses} | "
            f"{aw:+,.0f} | {al:+,.0f} | {ratio:.2f}x | "
            f"{r.get('avg_holding_days', 0):.1f} |"
        )
    avg_ratio = weighted_ratio_num / max(weighted_ratio_den, 1)
    # Required ratio for break-even gross at the average win rate of the run.
    overall_win_rate = sum(
        r.get("win_rate", 0.0) * r.get("trades", 0) for r in rows
    ) / max(sum(r.get("trades", 0) for r in rows), 1)
    required_ratio = (
        (1 - overall_win_rate) / overall_win_rate
        if overall_win_rate > 0 else float("inf")
    )
    lines.append("")
    lines.append(
        f"**Asymmetry check:** weighted-avg win:loss ratio = "
        f"**{avg_ratio:.2f}x**. At a win rate of "
        f"{overall_win_rate * 100:.1f}% the system needs "
        f"**>= {required_ratio:.2f}x** to be gross-flat. "
        + (
            "Asymmetry is sufficient — losses aren't the killer."
            if avg_ratio >= required_ratio else
            f"**Asymmetry is INSUFFICIENT by "
            f"{(required_ratio - avg_ratio):.2f}x.** Winners are being "
            f"cut too early or stops are too wide relative to targets."
        )
    )
    return "\n".join(lines)


def target_cost_histogram(report: Dict[str, Any]) -> Optional[str]:
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    if not rows or "target_cost_ratios" not in rows[0]:
        return None
    all_r: List[float] = []
    for r in rows:
        all_r.extend(r.get("target_cost_ratios", []))
    if not all_r:
        return "_(no executed trades had a valid target/cost ratio)_"
    bins = [0, 3, 5, 7, 10, 15, 25, 50, 100, float("inf")]
    counts = [0] * (len(bins) - 1)
    for v in all_r:
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                break
    total = sum(counts)
    lines = [
        f"_{total} executed trades; gate threshold is 3×._",
        "",
        "| target/cost band | trades | share |",
        "|---|---:|---:|",
    ]
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        if hi == float("inf"):
            band = f"≥ {lo:.0f}×"
        else:
            band = f"{lo:.0f}–{hi:.0f}×"
        share = counts[i] / total * 100 if total else 0.0
        lines.append(f"| {band} | {counts[i]} | {share:.1f}% |")
    below = sum(1 for v in all_r if v < 3)
    lines.append("")
    lines.append(
        f"**Sanity check:** {below} of {total} executed trades had a "
        f"target/cost ratio BELOW 3× — these should have been refused "
        f"by the gate. {'Gate firing correctly.' if below == 0 else 'Gate is buggy or being bypassed.'}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Q2 — skip-counter activity.
# ---------------------------------------------------------------------------

def skip_counter_table(report: Dict[str, Any]) -> str:
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    if not rows:
        return "_(no regime_on data)_"
    keys = sorted({k for r in rows for k in r.get("skip_counters", {})})
    header = "| window | trades |" + "".join(f" {k} |" for k in keys)
    sep    = "|---|---:|" + "".join("---:|" for _ in keys)
    out = [header, sep]
    totals: Dict[str, int] = {k: 0 for k in keys}
    total_trades = 0
    for r in rows:
        sc = r.get("skip_counters", {})
        row = (f"| {r['window']} | {r['trades']} |"
               + "".join(f" {sc.get(k, 0)} |" for k in keys))
        out.append(row)
        for k in keys:
            totals[k] += sc.get(k, 0)
        total_trades += r["trades"]
    out.append(
        f"| **TOTAL** | **{total_trades}** |"
        + "".join(f" **{totals[k]}** |" for k in keys)
    )
    return "\n".join(out)


def skip_counter_verdict(report: Dict[str, Any]) -> str:
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    if not rows:
        return ""
    totals: Dict[str, int] = {}
    total_trades = 0
    for r in rows:
        for k, v in r.get("skip_counters", {}).items():
            totals[k] = totals.get(k, 0) + v
        total_trades += r["trades"]
    parts = []
    mp = totals.get("min_profit", 0)
    if total_trades > 0:
        ratio = mp / total_trades
        if mp == 0:
            parts.append(
                f"- `min_profit` gate REFUSED 0 trades vs {total_trades} executed. "
                "The 3x cost gate is effectively a no-op — every signal that "
                "fired passed the gate. Either the gate is too lenient or "
                "the signal generator is producing only setups that mechanically "
                "clear costs (high-ATR universe symbols are sized small)."
            )
        elif ratio < 0.05:
            parts.append(
                f"- `min_profit` gate refused {mp} candidate entries "
                f"({ratio*100:.1f}% of executed count). Gate is active but "
                f"barely. Most signals pass 3x cost; either tighten the "
                f"multiple or accept the gate isn't your edge filter."
            )
        else:
            parts.append(
                f"- `min_profit` gate refused {mp} candidates "
                f"({ratio*100:.1f}% of executed count). Gate is doing real work."
            )
    vix = totals.get("vix_gate", 0) + totals.get("regime_block_all", 0)
    if vix > 0:
        parts.append(
            f"- Regime/VIX gates blocked {vix} scan-symbol-days from entering. "
            "Confirms the VIX gate is wired and firing; check whether ON vs "
            "OFF Δ is positive (good) or negative (gate is preventing winners)."
        )
    rbg = totals.get("regime_block_group", 0)
    if rbg > 0:
        parts.append(
            f"- ELEVATED VIX blocked `high_beta_cyclicals` {rbg} times. "
            "Inspect per_group P&L for that bucket to know if the block "
            "saved or cost money."
        )
    mpp = totals.get("max_position_pct", 0)
    if mpp > 0:
        parts.append(
            f"- `max_position_pct` clipped {mpp} candidate qty values. "
            "Most are clamps not refusals (qty reduced, position still taken)."
        )
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Q3 — per-group + per-regime summed across all regime_on windows.
# ---------------------------------------------------------------------------

def _sum_bucket(report: Dict[str, Any], field: str) -> Dict[str, Dict[str, float]]:
    rows = [r for r in report.get("per_window", []) if r["mode"] == "regime_on"]
    totals: Dict[str, Dict[str, float]] = {}
    for r in rows:
        for key, vals in r.get(field, {}).items():
            t = totals.setdefault(key, {"trades": 0, "pnl": 0.0, "wins": 0})
            t["trades"] += vals.get("trades", 0)
            t["pnl"] += vals.get("pnl", 0.0)
            t["wins"] += vals.get("wins", 0)
    for k, v in totals.items():
        v["win_rate"] = (v["wins"] / v["trades"]) if v["trades"] else 0.0
        v["avg_net_per_trade"] = (v["pnl"] / v["trades"]) if v["trades"] else 0.0
    return totals


def per_group_table(report: Dict[str, Any]) -> Tuple[str, List[str]]:
    g = _sum_bucket(report, "per_group")
    if not g:
        return "_(no per_group data)_", []
    lines = ["| group | trades | net P&L (Rs) | win % | avg net / trade (Rs) |",
             "|---|---:|---:|---:|---:|"]
    rows = sorted(g.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
    profitable: List[str] = []
    for name, v in rows:
        if v["pnl"] > 0:
            profitable.append(name)
        lines.append(
            f"| `{name}` | {int(v['trades'])} | {v['pnl']:+,.0f} | "
            f"{v['win_rate']*100:.1f}% | {v['avg_net_per_trade']:+,.1f} |"
        )
    return "\n".join(lines), profitable


def per_regime_table(report: Dict[str, Any]) -> str:
    parts = []
    for field, label in (
        ("per_vix_regime", "VIX regime"),
        ("per_market_trend", "Nifty trend"),
    ):
        agg = _sum_bucket(report, field)
        if not agg:
            continue
        parts.append(f"### {label}")
        parts.append("| bucket | trades | net P&L (Rs) | win % | avg net / trade (Rs) |")
        parts.append("|---|---:|---:|---:|---:|")
        for k, v in sorted(agg.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
            parts.append(
                f"| `{k}` | {int(v['trades'])} | {v['pnl']:+,.0f} | "
                f"{v['win_rate']*100:.1f}% | {v['avg_net_per_trade']:+,.1f} |"
            )
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Q4 — avg win Rs vs avg loss Rs (REQUIRES gross/charges per window OR
# per-trade log; flag as unanswerable from current JSON)
# ---------------------------------------------------------------------------

def implied_win_loss_table(report: Dict[str, Any]) -> str:
    """We have wins, trades, total_pnl per group. With two equations
    (wins*avg_win + losses*avg_loss = total_pnl; wins + losses = trades),
    avg_win and avg_loss are underdetermined. We CAN compute the
    *implied required avg loss* IF we assume a fixed avg_win — but
    that assumption is the whole question. So this section is honest
    about the limit and just surfaces win% + total net."""
    g = _sum_bucket(report, "per_group")
    if not g:
        return "_(no per_group data)_"
    lines = ["The existing JSON does not carry per-trade `pnl` or "
             "`gross_pnl`/`charges`, so we cannot decompose net P&L into "
             "average winning trade Rs vs average losing trade Rs. What "
             "the JSON CAN reveal:",
             "",
             "| group | wins | losses | net P&L (Rs) | implied avg per trade |",
             "|---|---:|---:|---:|---:|"]
    for name, v in sorted(g.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
        wins = int(v["wins"])
        losses = int(v["trades"] - v["wins"])
        avg = v["avg_net_per_trade"]
        lines.append(
            f"| `{name}` | {wins} | {losses} | {v['pnl']:+,.0f} | {avg:+,.1f} |"
        )
    lines.append("")
    lines.append(
        "The pattern `low win rate + small per-trade loss` IS the "
        "classic trend-following profile, but until we see actual avg-win "
        "vs avg-loss numbers we can't tell if the asymmetry is correct "
        "(few big wins ≫ many small losses) or broken (small wins "
        "smaller than small losses)."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def render(report_path: Path, report: Dict[str, Any]) -> str:
    pwt, has_gross = per_window_table(report)
    sct = skip_counter_table(report)
    sct_verdict = skip_counter_verdict(report)
    pgt, profitable_groups = per_group_table(report)
    prt = per_regime_table(report)
    iwl = implied_win_loss_table(report)

    bh = report.get("baseline_buy_and_hold", {})
    fd = report.get("baseline_fd_7pct", {})
    strat_net = report.get("strategy_net_pnl", 0.0)
    strat_ret = report.get("strategy_ret_pct", 0.0)

    parts: List[str] = []
    parts.append(f"# Walk-Forward Diagnosis — {Path(report_path).name}")
    parts.append("")
    parts.append(f"Period: **{report.get('overall_start')}** to **{report.get('overall_end')}**.")
    parts.append(f"Strategy net (regime ON): **Rs {strat_net:+,.2f}** "
                 f"({strat_ret*100:+.2f}%).")
    parts.append(
        f"Baseline buy-and-hold: Rs {bh.get('pnl_net', 0):+,.2f} "
        f"({bh.get('ret_pct', 0)*100:+.2f}%). "
        f"7% FD: Rs {fd.get('pnl_net', 0):+,.2f} "
        f"({fd.get('ret_pct', 0)*100:+.2f}%)."
    )
    parts.append("")
    # Detect richness of the JSON and adjust the preamble accordingly.
    rich = bool(report.get("per_window") and "gross_pnl" in report["per_window"][0])
    holdout = report.get("holdout_from")
    if holdout:
        parts.append(f"**Holdout in effect:** windows whose test period starts on or after `{holdout}` are excluded from this run (final-exam protection).")
        parts.append("")
    if rich:
        parts.append(
            "_JSON includes per-window `gross_pnl`, `total_charges`, "
            "`avg_holding_days`, `avg_win`, `avg_loss`, and per-trade "
            "`target_cost_ratios`. All four diagnostic questions are answerable._"
        )
    else:
        parts.append("## What this JSON can / can't tell us")
        parts.append("")
        parts.append("**Can:** per-window net P&L (ON / OFF), skip-counter activity, per-group + per-regime + per-trend P&L sums, win-rate breakdowns.")
        parts.append("")
        parts.append("**Can't (NOT in this JSON):**")
        parts.append("- per-window `gross_pnl` and `total_charges` — needed to answer Q1 (cost-eaten vs gross-negative)")
        parts.append("- per-window `avg_holding_days` — needed for Q3 holding-days line")
        parts.append("- per-trade `pnl`/`gross_pnl` — needed for Q4 avg-win-Rs vs avg-loss-Rs and a target/cost-ratio histogram")
        parts.append("")
        parts.append(
            "The walkforward writer has been updated to persist these fields. "
            "One re-run with the same config produces a JSON that answers every "
            "open question."
        )
    parts.append("")
    parts.append("## Q1 — per window: gross vs charges, ON vs OFF")
    parts.append("")
    parts.append(pwt)
    parts.append("")
    verdict = cost_eaten_verdict(report)
    if verdict:
        parts.append(verdict)
    else:
        parts.append(
            "**Gross vs charges UNAVAILABLE.** ON vs OFF Δ is informative on "
            "its own: where ON beats OFF the regime gate is adding value; "
            "where ON underperforms OFF the gate is filtering winners. "
            "Across all windows in this report the cumulative ON-OFF Δ is "
            "the **Total** row above."
        )
    parts.append("")
    parts.append("## Q2 — gate activity (regime_on runs only)")
    parts.append("")
    parts.append(sct)
    parts.append("")
    if sct_verdict:
        parts.append(sct_verdict)
        parts.append("")
    parts.append("## Q3 — per-group totals across all regime_on windows")
    parts.append("")
    parts.append(pgt)
    parts.append("")
    if profitable_groups:
        parts.append(
            f"**Net-positive groups across the full window set:** "
            + ", ".join(f"`{g}`" for g in profitable_groups) + "."
        )
    else:
        parts.append(
            "**No universe group is net-positive across the full window set.** "
            "This rules out the 'one bucket is dragging everything down' "
            "hypothesis. The signal generator's edge is gross-too-small or "
            "gross-negative on every group we tested."
        )
    parts.append("")
    parts.append("### Per-regime")
    parts.append("")
    parts.append(prt)
    parts.append("## Q4 — avg win Rs vs avg loss Rs")
    parts.append("")
    wlt = win_loss_table(report)
    if wlt:
        parts.append(wlt)
        parts.append("")
    else:
        parts.append(iwl)
        parts.append("")
    hist = target_cost_histogram(report)
    if hist:
        parts.append("### Target/cost ratio distribution (executed trades)")
        parts.append("")
        parts.append(hist)
        parts.append("")
    if not rich:
        parts.append("---")
        parts.append("")
        parts.append("## How to complete the diagnosis")
        parts.append("")
        parts.append(
            "`scripts/run_walkforward.py` now also persists `gross_pnl`, "
            "`total_charges`, `avg_holding_days`, `avg_win`, `avg_loss`, "
            "and `target_cost_ratios` (per executed trade) in every "
            "per_window entry. Re-run the same command (no other change "
            "is required) and re-run `scripts/diagnose_walkforward.py` "
            "against the new JSON — every blank above turns into a number."
        )
    return "\n".join(parts)


def main() -> int:
    report_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else _latest_report(Path("reports"))
    )
    report = _load(report_path)
    out = render(report_path, report)
    # Write next to the source report.
    out_md = report_path.with_name(
        report_path.stem.replace("walkforward", "diagnosis") + ".md"
    )
    out_md.write_text(out)
    print(out)
    print()
    print(f"\n(also written to {out_md})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
