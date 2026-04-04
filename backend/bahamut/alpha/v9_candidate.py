"""
Bahamut v9 — Confirmed Breakout Edge

Hypothesis: "Breakouts that HOLD are more reliable than raw breakouts."

The edge: when price breaks a 20-bar high AND holds above it for 3+ bars,
the move continues. Unconfirmed breakouts (that fail back below) are noise.

Data shows: confirmed breakouts return +0.56% over 10 bars vs
unconfirmed breakouts at -1.10%. That's a 1.66% edge per event.

This is structurally DIFFERENT from v5:
  v5 = EMA cross (lagging momentum indicator)
  v9 = price-action breakout + confirmation (structural event)

They should fire at different times:
  v5 fires DURING trends (after EMAs align)
  v9 fires at the START of new moves (price exceeds recent highs)
"""
import numpy as np
from dataclasses import dataclass
from bahamut.strategies.base import Signal


@dataclass
class BreakoutSignal:
    valid: bool = False
    direction: str = "NONE"
    entry_type: str = "breakout_confirmed"
    confidence: float = 0.0
    reason: str = ""
    breakout_level: float = 0.0


def detect_confirmed_breakout(
    candles: list,
    indicators: dict,
    lookback: int = 20,
    confirm_bars: int = 3,
) -> BreakoutSignal:
    """
    Detect a confirmed breakout — price breaks N-bar high and holds.

    candles: recent 30+ candles
    indicators: current indicators
    lookback: period to find the high to break (default 20)
    confirm_bars: how many bars it must hold above (default 3)
    """
    sig = BreakoutSignal()

    if not candles or len(candles) < lookback + confirm_bars + 2:
        return sig

    close = indicators.get("close", 0)
    atr = indicators.get("atr_14", 0)
    ema_200 = indicators.get("ema_200", 0)

    if close <= 0 or atr <= 0:
        return sig

    # ── FIND THE BREAKOUT LEVEL ──
    # High of the lookback bars BEFORE the confirmation window
    ref_candles = candles[-(lookback + confirm_bars + 1):-(confirm_bars + 1)]
    if len(ref_candles) < lookback - 2:
        return sig

    ref_high = max(c["high"] for c in ref_candles)

    # ── CHECK CONFIRMATION ──
    # The last confirm_bars candles must all close above the breakout level
    confirm_candles = candles[-(confirm_bars + 1):-1]  # bars before current
    current = candles[-1]

    if len(confirm_candles) < confirm_bars:
        return sig

    # All confirmation bars must close above the reference high
    all_held = all(c["close"] > ref_high * 0.995 for c in confirm_candles)  # 0.5% tolerance
    # Current bar also above
    current_above = current["close"] > ref_high * 0.995

    if not all_held or not current_above:
        return sig

    # ── QUALITY FILTERS ──
    quality = 0.5

    # Distance above breakout level (stronger breakout = higher quality)
    dist_above = (close - ref_high) / atr if atr > 0 else 0
    if dist_above > 0.5:
        quality += min(0.2, dist_above * 0.1)

    # Not too extended (avoid buying tops)
    if dist_above > 3.0:
        sig.reason = "too extended above breakout"
        return sig

    # Volume confirmation: recent bars have expanding range
    recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
    prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]]
    if prior_ranges and recent_ranges:
        range_expansion = np.mean(recent_ranges) / (np.mean(prior_ranges) + 1e-10)
        if range_expansion > 1.2:
            quality += 0.1  # Range expanding — healthy breakout

    # Bullish closes in confirmation window
    bull_count = sum(1 for c in confirm_candles if c["close"] > c["open"])
    if bull_count >= 2:
        quality += 0.1

    # Not in crash (basic safety — but NOT requiring bull regime like v5)
    if ema_200 > 0 and close < ema_200 * 0.90:
        sig.reason = "deep below EMA200, potential crash"
        return sig

    sig.valid = True
    sig.direction = "LONG"
    sig.confidence = round(min(1.0, quality), 3)
    sig.breakout_level = round(ref_high, 2)
    sig.reason = f"20-bar high breakout at ${ref_high:,.0f}, held {confirm_bars} bars, dist={dist_above:.1f}ATR"

    return sig


class V9Breakout:
    """Strategy wrapper for the execution framework."""

    def __init__(self):
        self.name = "v9_breakout"
        self.sl_pct = 0.10       # 10% SL — wider for BTC noise
        self.tp_pct = 0.25       # 25% TP — 2.5:1 R:R
        self.max_hold = 40       # ~6.7 days
        self.risk_pct = 0.02

    def evaluate(self, candles, indicators, prev_indicators=None, asset="BTCUSD"):
        sig = detect_confirmed_breakout(candles, indicators)
        if sig.valid:
            bar_ts = candles[-1].get("datetime", "") if candles else ""
            interval = indicators.get("_interval", "4h") if indicators else "4h"

            # Tighter SL/TP for faster timeframes
            if interval in ("15m", "5m", "1m"):
                sl = 0.02    # 2% SL (was 10%)
                tp = 0.05    # 5% TP (was 25%)
                hold = 40    # 40 × 15m = 10 hours
            else:
                sl = self.sl_pct   # 10%
                tp = self.tp_pct   # 25%
                hold = self.max_hold  # 40 × 4H = 6.7 days

            return Signal(
                strategy=self.name,
                asset=asset,
                direction=sig.direction,
                sl_pct=sl,
                tp_pct=tp,
                max_hold_bars=hold,
                quality=sig.confidence,
                reason=sig.reason,
                signal_id=f"{self.name}:{asset}:{bar_ts}",
            )
        return None
