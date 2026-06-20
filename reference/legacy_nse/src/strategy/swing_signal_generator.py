"""
Swing Signal Generator: Daily EMA Pullback + MACD Confirmation
==============================================================
Long-only strategy for CNC delivery trades (2-10 day holds).

Entry requires ALL 6 conditions to be true (conjunction, not weighted):
  1. Close > EMA(100) — weekly uptrend proxy
  2. EMA(20) > EMA(50) — daily uptrend confirmed
  3. Close within X% of EMA(20) — pullback zone
  4. MACD histogram rising (today > yesterday) — momentum resuming
  5. RSI(14) between 40-65 — healthy pullback, not overbought
  6. Volume > 80% of 50-day average — participation confirmation
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from src.indicators.technical import (
    compute_adx,
    compute_atr,
    compute_ema,
    compute_macd,
    compute_rsi,
)


class SwingSignalType(Enum):
    BUY = "BUY"
    HOLD = "HOLD"


@dataclass
class SwingSignal:
    type: SwingSignalType
    reasons: List[str]
    atr: Optional[float] = None
    price: float = 0.0
    symbol: str = ""


class SwingSignalGenerator:
    """
    Daily timeframe pullback signal generator.

    All 6 conditions must pass for a BUY signal. Long-only.
    """

    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self, config: Dict[str, Any]):
        self.ema_fast = config.get("ema_fast", 20)
        self.ema_slow = config.get("ema_slow", 50)
        self.ema_trend = config.get("ema_trend", 100)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_low = config.get("rsi_low", 40)
        self.rsi_high = config.get("rsi_high", 65)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.pullback_zone_pct = config.get("pullback_zone_pct", 0.02)
        self.volume_ma_period = config.get("volume_ma_period", 50)
        self.volume_threshold = config.get("volume_threshold", 0.8)
        self.min_adx = config.get("min_adx", 15)
        self.entry_days: List[int] = config.get("entry_days", [0, 1, 2])  # Mon/Tue/Wed

    def generate_signal(self, symbol: str, df: pd.DataFrame,
                        current_weekday: Optional[int] = None) -> SwingSignal:
        """
        Evaluate the 6-condition entry on a daily OHLCV DataFrame.

        Args:
            symbol: Stock symbol.
            df: Daily OHLCV DataFrame with columns: open, high, low, close, volume.
                Must have at least ema_trend + 5 rows for meaningful indicators.
            current_weekday: Day of week (0=Mon, 6=Sun). If provided, entry_days filter applied.

        Returns:
            SwingSignal with BUY or HOLD.
        """
        reasons: List[str] = []
        conditions_met = 0
        total_conditions = 6

        # --- Pre-gate: Day-of-week filter ---
        if current_weekday is not None and current_weekday not in self.entry_days:
            day_name = self.DAY_NAMES[current_weekday]
            allowed = ", ".join(self.DAY_NAMES[d] for d in self.entry_days)
            reasons.append(f"[SKIP] No entries on {day_name} (allowed: {allowed})")
            return SwingSignal(SwingSignalType.HOLD, reasons, symbol=symbol)

        min_rows = self.ema_trend + 5
        if df is None or len(df) < min_rows:
            reasons.append(f"Insufficient data ({len(df) if df is not None else 0} < {min_rows})")
            return SwingSignal(SwingSignalType.HOLD, reasons, symbol=symbol)

        close = df["close"]
        volume = df["volume"]
        current_close = float(close.iloc[-1])

        # Compute indicators
        ema_fast = compute_ema(close, self.ema_fast)
        ema_slow = compute_ema(close, self.ema_slow)
        ema_trend = compute_ema(close, self.ema_trend)
        rsi = compute_rsi(close, self.rsi_period)
        _, _, macd_hist = compute_macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        atr = compute_atr(df["high"], df["low"], close, period=14)

        ema_fast_val = float(ema_fast.iloc[-1])
        ema_slow_val = float(ema_slow.iloc[-1])
        ema_trend_val = float(ema_trend.iloc[-1])
        rsi_val = float(rsi.iloc[-1])
        hist_today = float(macd_hist.iloc[-1])
        hist_yesterday = float(macd_hist.iloc[-2])
        atr_val = float(atr.iloc[-1])

        # Guard against NaN in any indicator
        values = [ema_fast_val, ema_slow_val, ema_trend_val, rsi_val,
                  hist_today, hist_yesterday, atr_val]
        if any(pd.isna(v) for v in values):
            reasons.append("NaN detected in indicators")
            return SwingSignal(SwingSignalType.HOLD, reasons, symbol=symbol)

        # --- Pre-gate: ADX regime filter ---
        adx = compute_adx(df["high"], df["low"], close, period=14)
        adx_val = float(adx.iloc[-1])
        if pd.isna(adx_val):
            reasons.append("NaN in ADX")
            return SwingSignal(SwingSignalType.HOLD, reasons, atr=atr_val,
                               price=current_close, symbol=symbol)
        if adx_val < self.min_adx:
            reasons.append(f"[GATE] ADX {adx_val:.1f} < {self.min_adx} (RANGING)")
            return SwingSignal(SwingSignalType.HOLD, reasons, atr=atr_val,
                               price=current_close, symbol=symbol)
        reasons.append(f"[GATE] ADX {adx_val:.1f} >= {self.min_adx} (TRENDING)")

        # Volume moving average
        vol_ma = float(volume.rolling(self.volume_ma_period).mean().iloc[-1])
        current_vol = float(volume.iloc[-1])
        if pd.isna(vol_ma) or pd.isna(current_vol):
            reasons.append("NaN in volume data")
            return SwingSignal(SwingSignalType.HOLD, reasons, symbol=symbol)

        # --- Condition 1: Close > EMA(100) — uptrend ---
        if current_close > ema_trend_val:
            conditions_met += 1
            reasons.append(f"[OK] Close {current_close:.2f} > EMA({self.ema_trend}) {ema_trend_val:.2f}")
        else:
            reasons.append(f"[FAIL] Close {current_close:.2f} <= EMA({self.ema_trend}) {ema_trend_val:.2f}")

        # --- Condition 2: EMA(20) > EMA(50) — daily uptrend ---
        if ema_fast_val > ema_slow_val:
            conditions_met += 1
            reasons.append(f"[OK] EMA({self.ema_fast}) {ema_fast_val:.2f} > EMA({self.ema_slow}) {ema_slow_val:.2f}")
        else:
            reasons.append(f"[FAIL] EMA({self.ema_fast}) {ema_fast_val:.2f} <= EMA({self.ema_slow}) {ema_slow_val:.2f}")

        # --- Condition 3: Close within X% of EMA(20) — pullback zone ---
        pullback_dist = abs(current_close - ema_fast_val) / ema_fast_val
        if pullback_dist <= self.pullback_zone_pct:
            conditions_met += 1
            reasons.append(f"[OK] Pullback {pullback_dist:.2%} <= {self.pullback_zone_pct:.0%}")
        else:
            reasons.append(f"[FAIL] Pullback {pullback_dist:.2%} > {self.pullback_zone_pct:.0%}")

        # --- Condition 4: MACD histogram rising (momentum resuming) ---
        # For pullback strategies, we want to see momentum improving,
        # not necessarily a zero cross (which is too rare on daily bars).
        if hist_today > hist_yesterday:
            conditions_met += 1
            reasons.append(f"[OK] MACD hist rising: {hist_yesterday:.4f} -> {hist_today:.4f}")
        else:
            reasons.append(f"[FAIL] MACD hist not rising: {hist_yesterday:.4f} -> {hist_today:.4f}")

        # --- Condition 5: RSI between 40-65 ---
        if self.rsi_low <= rsi_val <= self.rsi_high:
            conditions_met += 1
            reasons.append(f"[OK] RSI {rsi_val:.1f} in [{self.rsi_low}-{self.rsi_high}]")
        else:
            reasons.append(f"[FAIL] RSI {rsi_val:.1f} outside [{self.rsi_low}-{self.rsi_high}]")

        # --- Condition 6: Volume > 80% of 50-day average ---
        if vol_ma > 0 and current_vol >= self.volume_threshold * vol_ma:
            conditions_met += 1
            vol_ratio = current_vol / vol_ma
            reasons.append(f"[OK] Volume ratio {vol_ratio:.2f}x >= {self.volume_threshold}")
        else:
            vol_ratio = current_vol / vol_ma if vol_ma > 0 else 0
            reasons.append(f"[FAIL] Volume ratio {vol_ratio:.2f}x < {self.volume_threshold}")

        # All 6 must pass
        if conditions_met == total_conditions:
            return SwingSignal(
                type=SwingSignalType.BUY,
                reasons=reasons,
                atr=atr_val,
                price=current_close,
                symbol=symbol,
            )

        reasons.append(f"Signal: {conditions_met}/{total_conditions} conditions met")
        return SwingSignal(
            type=SwingSignalType.HOLD,
            reasons=reasons,
            atr=atr_val,
            price=current_close,
            symbol=symbol,
        )
