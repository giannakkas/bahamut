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
    # Phase 3 Item 9: carry forward ATR + ref_high distance so evaluate()
    # can compute a structure-aware, volatility-scaled SL without
    # re-reading the candles.
    atr: float = 0.0
    dist_above_atr: float = 0.0


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
    sig.atr = round(atr, 6)
    sig.dist_above_atr = round(dist_above, 4)
    sig.reason = f"20-bar high breakout at ${ref_high:,.0f}, held {confirm_bars} bars, dist={dist_above:.1f}ATR"

    return sig


def detect_confirmed_breakdown(
    candles: list,
    indicators: dict,
    lookback: int = 20,
    confirm_bars: int = 3,
) -> BreakoutSignal:
    """Detect a confirmed breakdown SHORT — price breaks N-bar LOW and holds below.

    Mirror of detect_confirmed_breakout for SHORT setups.

    candles: recent 30+ candles
    indicators: current indicators
    lookback: period to find the low to break (default 20)
    confirm_bars: how many bars it must hold below (default 3)
    """
    sig = BreakoutSignal()

    if not candles or len(candles) < lookback + confirm_bars + 2:
        return sig

    close = indicators.get("close", 0)
    atr = indicators.get("atr_14", 0)
    ema_200 = indicators.get("ema_200", 0)

    if close <= 0 or atr <= 0:
        return sig

    # Find the breakdown level: LOW of the lookback bars BEFORE confirmation window
    ref_candles = candles[-(lookback + confirm_bars + 1):-(confirm_bars + 1)]
    if len(ref_candles) < lookback - 2:
        return sig

    ref_low = min(c["low"] for c in ref_candles)

    # Check confirmation: last confirm_bars candles must all close below ref_low
    confirm_candles = candles[-(confirm_bars + 1):-1]
    current = candles[-1]

    if len(confirm_candles) < confirm_bars:
        return sig

    all_held = all(c["close"] < ref_low * 1.005 for c in confirm_candles)  # 0.5% tolerance
    current_below = current["close"] < ref_low * 1.005

    if not all_held or not current_below:
        return sig

    # Quality filters
    quality = 0.5

    dist_below = (ref_low - close) / atr if atr > 0 else 0
    if dist_below > 0.5:
        quality += min(0.2, dist_below * 0.1)

    # Not too extended below (avoid shorting lows)
    if dist_below > 3.0:
        sig.reason = "too extended below breakdown"
        return sig

    # Range expansion check
    recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
    prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]]
    if prior_ranges and recent_ranges:
        range_expansion = np.mean(recent_ranges) / (np.mean(prior_ranges) + 1e-10)
        if range_expansion > 1.2:
            quality += 0.1

    # Bearish closes in confirmation window
    bear_count = sum(1 for c in confirm_candles if c["close"] < c["open"])
    if bear_count >= 2:
        quality += 0.1

    # Not in a raging bull (basic safety)
    if ema_200 > 0 and close > ema_200 * 1.10:
        sig.reason = "deep above EMA200, not a breakdown"
        return sig

    sig.valid = True
    sig.direction = "SHORT"
    sig.confidence = round(min(1.0, quality), 3)
    sig.breakout_level = round(ref_low, 2)
    sig.atr = round(atr, 6)
    sig.dist_above_atr = round(dist_below, 4)
    sig.reason = f"20-bar low breakdown at ${ref_low:,.0f}, held {confirm_bars} bars below, dist={dist_below:.1f}ATR"

    return sig


class V9Breakout:
    """Strategy wrapper for the execution framework.

    Phase 3 Item 9: SL/TP/hold are now ATR-aware and structure-aware.

    SL reasoning:
      - ATR floor: SL must be at least atr_mult * ATR / close (volatility-scaled).
      - Percentage floor/cap: clamp to [sl_floor, sl_cap] so we never submit
        a 0.2% stop that gets hit on noise OR a 30% stop that's absurd.
      - Structural cap: SL is also capped by the distance to (ref_high * 0.995)
        — a breakout that retraces below that level is invalidated, so a
        wider SL makes no sense.
      The *tightest* of those three wins, with a lower floor.

    TP reasoning:
      - R:R floor of 2.0x the final SL (was fixed 2.5x).
      - ATR target: target_atr_mult * ATR / close as a secondary floor.
      - TP still capped at tp_cap to avoid unrealistic targets on 4H.

    Hold reasoning:
      - 4H: tightened from 40 to 20 bars (3.3 days), matching the
        proven 10-bar horizon from the strategy docstring with 2x margin.
      - 15m: tightened from 40 to 24 bars (6 hours), matching confirmed
        breakout continuation window on faster timeframe.

    Set BAHAMUT_V9_ADAPTIVE_SIZING=0 in env to revert to fixed 10%/25%/40
    legacy behavior for A/B comparison.
    """

    def __init__(self):
        self.name = "v9_breakout"
        self.sl_pct = 0.10       # Legacy fixed — used only when adaptive disabled
        self.tp_pct = 0.25
        self.max_hold = 40
        self.risk_pct = 0.02

    def evaluate(self, candles, indicators, prev_indicators=None, asset="BTCUSD"):
        import os

        # Try breakout (LONG) first, then breakdown (SHORT)
        sig = detect_confirmed_breakout(candles, indicators)
        if not sig.valid:
            sig = detect_confirmed_breakdown(candles, indicators)
        if not sig.valid:
            return None

        bar_ts = candles[-1].get("datetime", "") if candles else ""
        interval = indicators.get("_interval", "4h") if indicators else "4h"
        close = float(indicators.get("close", 0))
        atr = float(sig.atr or indicators.get("atr_14", 0))
        ref_level = float(sig.breakout_level or 0)  # breakout high or breakdown low

        adaptive = os.environ.get("BAHAMUT_V9_ADAPTIVE_SIZING", "1") != "0"

        if not adaptive:
            # Legacy path — unchanged behavior
            if interval in ("15m", "5m", "1m"):
                sl, tp, hold = 0.02, 0.05, 40
            else:
                sl, tp, hold = self.sl_pct, self.tp_pct, self.max_hold
        else:
            # ── Phase 3 Item 9: adaptive sizing ──
            if interval in ("15m", "5m", "1m"):
                sl_floor = 0.006   # 0.6% minimum (was 0.2%)
                sl_cap = 0.025     # 2.5% max
                atr_mult = 1.8
                tp_floor = 0.008   # 0.8% min TP
                tp_cap = 0.06      # 6% max TP
                target_atr_mult = 2.5
                rr_floor = 2.0
                hold = 24          # ~6 hours (was 40)
            else:
                sl_floor = 0.035   # 3.5% min SL (was implicit 10%)
                sl_cap = 0.10      # 10% max
                atr_mult = 2.0
                tp_floor = 0.05    # 5% min TP
                tp_cap = 0.25
                target_atr_mult = 3.5
                rr_floor = 2.0
                hold = 20          # 3.3 days (was 40)

            # ATR-based SL
            if close > 0 and atr > 0:
                sl_atr = (atr_mult * atr) / close
            else:
                sl_atr = sl_floor
            sl = max(sl_atr, sl_floor)
            sl = min(sl, sl_cap)

            # Structural cap: SL cannot be wider than distance-to-invalidation level
            # For LONG: ref_level * 0.995 (breakout retraced = invalidated)
            # For SHORT: ref_level * 1.005 (breakdown reclaimed = invalidated)
            if close > 0 and ref_level > 0:
                if sig.direction == "LONG":
                    invalidation_level = ref_level * 0.995
                    struct_dist = (close - invalidation_level) / close
                else:
                    invalidation_level = ref_level * 1.005
                    struct_dist = (invalidation_level - close) / close
                if struct_dist > sl_floor:
                    sl = min(sl, struct_dist)

            # Ensure we still respect the absolute minimum
            sl = max(sl, sl_floor)

            # Adaptive TP: max of (RR × SL, ATR target, floor), capped
            tp_rr = rr_floor * sl
            if close > 0 and atr > 0:
                tp_atr = (target_atr_mult * atr) / close
            else:
                tp_atr = tp_floor
            tp = max(tp_rr, tp_atr, tp_floor)
            tp = min(tp, tp_cap)

        return Signal(
            strategy=self.name,
            asset=asset,
            direction=sig.direction,
            sl_pct=round(sl, 4),
            tp_pct=round(tp, 4),
            max_hold_bars=hold,
            quality=sig.confidence,
            reason=sig.reason + (f" | adaptive SL={sl:.3f} TP={tp:.3f} hold={hold}"
                                 if adaptive else ""),
            signal_id=f"{self.name}:{asset}:{bar_ts}",
        )
