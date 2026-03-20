"""
Bahamut v5 — Pullback Entry Engine

The core alpha hypothesis:
  In a confirmed trend, price pulls back to value (EMA zone) before continuing.
  Enter AFTER the pullback stabilizes, not during the impulse.

LONG setup (BULL regime):
  1. Trend confirmed (EMA20 > EMA50 > EMA200, or ADX > 25)
  2. Price has pulled back toward EMA20-EMA50 zone
  3. RSI has reset (35-55 range, not overbought)
  4. Current candle shows rejection (lower wick, bullish close)
  5. Not exhausted (not 5+ consecutive direction candles)

SHORT setup mirrors in BEAR regime.

This replaces the v2 approach of "score everything and trade when score > 15"
with a specific, testable market behavior pattern.
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class PullbackSignal:
    valid: bool = False
    direction: str = "NONE"       # LONG or SHORT
    quality: float = 0.0          # 0-1
    entry_type: str = "none"      # pullback, deep_pullback, ema_bounce
    reason: str = ""
    stop_level: float = 0.0       # Structure-based SL
    target_level: float = 0.0     # Structure-based TP


def detect_pullback(
    candles: list,
    indicators: dict,
    regime: str,
    structure: object = None,
) -> PullbackSignal:
    """
    Detect pullback entry opportunity.

    candles: recent 30-50 candles
    indicators: from compute_indicators()
    regime: "BULL" or "BEAR" from regime_filter
    structure: StructureResult (optional, for S/R levels)
    """
    sig = PullbackSignal()

    if regime not in ("BULL", "BEAR") or len(candles) < 15:
        return sig

    close = indicators.get("close", 0)
    rsi = indicators.get("rsi_14", 50)
    adx = indicators.get("adx_14", 20)
    atr = indicators.get("atr_14", close * 0.02)
    ema_20 = indicators.get("ema_20", close)
    ema_50 = indicators.get("ema_50", close)
    ema_200 = indicators.get("ema_200", close)
    stoch_k = indicators.get("stoch_k", 50)
    macd_hist = indicators.get("macd_histogram", 0)

    if close <= 0 or atr <= 0:
        return sig

    is_bull = regime == "BULL"

    # ── 1. TREND CONFIRMATION ──
    trend_score = 0

    if is_bull:
        if ema_20 > ema_50 > ema_200:
            trend_score += 2  # Perfect EMA alignment
        elif ema_20 > ema_50:
            trend_score += 1  # Partial alignment
        if close > ema_200:
            trend_score += 1
    else:
        if ema_20 < ema_50 < ema_200:
            trend_score += 2
        elif ema_20 < ema_50:
            trend_score += 1
        if close < ema_200:
            trend_score += 1

    if adx > 25:
        trend_score += 1

    if trend_score < 2:
        sig.reason = "trend too weak"
        return sig

    # ── 2. PULLBACK DETECTION ──
    # Distance from EMA20 in ATR units
    dist_ema20 = (close - ema_20) / atr if is_bull else (ema_20 - close) / atr
    dist_ema50 = (close - ema_50) / atr if is_bull else (ema_50 - close) / atr

    pullback_quality = 0.0

    if is_bull:
        # LONG: price should be near or slightly below EMA20/EMA50
        if -0.5 <= dist_ema20 <= 0.8:
            pullback_quality += 0.4  # Near EMA20 — sweet spot
            sig.entry_type = "pullback"
        elif -1.5 <= dist_ema20 < -0.5:
            pullback_quality += 0.3  # Below EMA20 — deeper pullback
            sig.entry_type = "deep_pullback"
        elif 0.8 < dist_ema20 <= 1.5:
            pullback_quality += 0.1  # Slightly above — less ideal
            sig.entry_type = "ema_bounce"
        else:
            sig.reason = f"price too far from EMA20 ({dist_ema20:.1f} ATR)"
            return sig

        # Bonus: near EMA50 (deeper value zone)
        if -0.5 <= dist_ema50 <= 0.5:
            pullback_quality += 0.15
    else:
        # SHORT mirror
        if -0.5 <= dist_ema20 <= 0.8:
            pullback_quality += 0.4
            sig.entry_type = "pullback"
        elif -1.5 <= dist_ema20 < -0.5:
            pullback_quality += 0.3
            sig.entry_type = "deep_pullback"
        elif 0.8 < dist_ema20 <= 1.5:
            pullback_quality += 0.1
            sig.entry_type = "ema_bounce"
        else:
            sig.reason = f"price too far from EMA20 ({dist_ema20:.1f} ATR)"
            return sig

        if -0.5 <= dist_ema50 <= 0.5:
            pullback_quality += 0.15

    # ── 3. RSI RESET CHECK ──
    rsi_quality = 0.0
    if is_bull:
        if 35 <= rsi <= 55:
            rsi_quality = 0.2  # RSI has cooled — room to run up
        elif 55 < rsi <= 65:
            rsi_quality = 0.1  # OK but less room
        elif rsi > 70:
            sig.reason = f"RSI overbought ({rsi:.0f})"
            return sig  # Don't buy overbought in a pullback strategy
    else:
        if 45 <= rsi <= 65:
            rsi_quality = 0.2
        elif 35 <= rsi < 45:
            rsi_quality = 0.1
        elif rsi < 30:
            sig.reason = f"RSI oversold ({rsi:.0f})"
            return sig

    # ── 4. CANDLE REJECTION / STABILIZATION ──
    candle_quality = 0.0
    curr = candles[-1]
    body = abs(curr["close"] - curr["open"])
    total_range = curr["high"] - curr["low"]

    if total_range > 0:
        body_ratio = body / total_range

        if is_bull:
            lower_wick = min(curr["open"], curr["close"]) - curr["low"]
            wick_ratio = lower_wick / total_range
            # Bullish rejection: long lower wick, close near high
            if wick_ratio > 0.4 and curr["close"] > curr["open"]:
                candle_quality = 0.2  # Strong rejection candle
            elif curr["close"] > curr["open"]:
                candle_quality = 0.1  # At least bullish close
            elif body_ratio < 0.3:
                candle_quality = 0.05  # Doji — indecision, acceptable
        else:
            upper_wick = curr["high"] - max(curr["open"], curr["close"])
            wick_ratio = upper_wick / total_range
            if wick_ratio > 0.4 and curr["close"] < curr["open"]:
                candle_quality = 0.2
            elif curr["close"] < curr["open"]:
                candle_quality = 0.1
            elif body_ratio < 0.3:
                candle_quality = 0.05

    # ── 5. EXHAUSTION CHECK ──
    if len(candles) >= 5:
        if is_bull:
            # Check we're not in the middle of a sharp drop (5 red candles)
            red_count = sum(1 for c in candles[-5:] if c["close"] < c["open"])
            if red_count >= 5:
                sig.reason = "sharp selloff — don't catch falling knife"
                return sig
        else:
            green_count = sum(1 for c in candles[-5:] if c["close"] > c["open"])
            if green_count >= 5:
                sig.reason = "sharp rally — don't short into strength"
                return sig

    # ── 6. MACD CONFIRMATION ──
    macd_bonus = 0.0
    if is_bull and macd_hist > 0:
        macd_bonus = 0.05  # MACD histogram turning positive
    elif not is_bull and macd_hist < 0:
        macd_bonus = 0.05

    # ── 7. STRUCTURE CONFIRMATION ──
    structure_bonus = 0.0
    if structure:
        if structure.bos:
            structure_bonus += 0.1  # Break of structure in trend direction
        if is_bull and structure.structure_bias == "LONG":
            structure_bonus += 0.05
        elif not is_bull and structure.structure_bias == "SHORT":
            structure_bonus += 0.05
        if structure.near_key_level:
            structure_bonus += 0.05  # Near support/resistance

    # ── COMPUTE FINAL QUALITY ──
    total_quality = pullback_quality + rsi_quality + candle_quality + macd_bonus + structure_bonus
    sig.quality = round(min(1.0, total_quality), 3)

    # Minimum quality threshold
    if sig.quality < 0.35:
        sig.reason = f"quality too low ({sig.quality:.2f})"
        return sig

    sig.valid = True
    sig.direction = "LONG" if is_bull else "SHORT"

    # ── STOP AND TARGET LEVELS ──
    if is_bull:
        # SL below recent swing low or EMA50, whichever is closer
        if structure and structure.swing_lows:
            recent_support = max(l for l in structure.swing_lows if l < close) if \
                any(l < close for l in structure.swing_lows) else close - atr * 3
            sig.stop_level = min(recent_support - atr * 0.3, ema_50 - atr * 0.5)
        else:
            sig.stop_level = min(ema_50 - atr * 0.5, close - atr * 3)

        # TP at recent high or 3x risk
        risk = close - sig.stop_level
        sig.target_level = close + max(risk * 2.5, atr * 4)
    else:
        if structure and structure.swing_highs:
            recent_resistance = min(h for h in structure.swing_highs if h > close) if \
                any(h > close for h in structure.swing_highs) else close + atr * 3
            sig.stop_level = max(recent_resistance + atr * 0.3, ema_50 + atr * 0.5)
        else:
            sig.stop_level = max(ema_50 + atr * 0.5, close + atr * 3)

        risk = sig.stop_level - close
        sig.target_level = close - max(risk * 2.5, atr * 4)

    # Build reason
    parts = [sig.entry_type, f"q={sig.quality:.2f}"]
    if structure_bonus > 0:
        parts.append("struct_confirmed")
    if macd_bonus > 0:
        parts.append("macd_aligned")
    sig.reason = ", ".join(parts)

    return sig
