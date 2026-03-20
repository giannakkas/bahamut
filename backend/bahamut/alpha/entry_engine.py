"""
Bahamut v4 — Entry Quality Engine

Sits AFTER directional bias is known, BEFORE execution.
Scores entry quality to improve timing without killing trade frequency.

Entry types:
- pullback: trend is established, price has pulled back toward value
- breakout: price breaking compression or key level with momentum
- retest: price broke a level and is retesting it as new support/resistance
- momentum: strong directional move, chasing but with confirmation
- poor: exhausted, overextended, or no clear setup

Design rule: NEVER hard-block a trade. Instead:
- Adjust confidence
- Adjust position size
- Suggest delay
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class EntryQuality:
    entry_quality: float = 0.5          # 0-1 overall quality
    entry_type: str = "momentum"        # pullback/breakout/retest/momentum/poor
    should_delay_entry: bool = False     # Wait for better price?
    reason: str = ""
    confidence_adjustment: float = 0.0  # Added to base confidence (-0.15 to +0.15)
    size_adjustment: float = 1.0        # Multiply position size (0.5 to 1.2)


def score_entry(
    direction: str,
    indicators: dict,
    structure: object,  # StructureResult from structure_engine
    candles: list,
) -> EntryQuality:
    """
    Score entry quality for a given direction.
    
    direction: "LONG" or "SHORT"
    indicators: from compute_indicators()
    structure: StructureResult from analyze_structure()
    candles: recent candles (last 20-30)
    """
    result = EntryQuality()
    if direction not in ("LONG", "SHORT") or not candles or len(candles) < 5:
        result.entry_type = "poor"
        result.entry_quality = 0.2
        result.confidence_adjustment = -0.10
        return result

    close = indicators.get("close", 0)
    rsi = indicators.get("rsi_14", 50)
    atr = indicators.get("atr_14", close * 0.015)
    ema_20 = indicators.get("ema_20", close)
    ema_50 = indicators.get("ema_50", close)
    stoch_k = indicators.get("stoch_k", 50)
    bb_upper = indicators.get("bollinger_upper", close)
    bb_lower = indicators.get("bollinger_lower", close)
    bb_mid = indicators.get("bollinger_mid", close)
    adx = indicators.get("adx_14", 20)
    macd_hist = indicators.get("macd_histogram", 0)

    is_long = direction == "LONG"
    quality_points = 0.0
    reasons = []

    # ── A. PULLBACK ENTRY DETECTION ──
    pullback_score = _score_pullback(is_long, close, ema_20, ema_50, atr, rsi, stoch_k)
    if pullback_score > 0.6:
        result.entry_type = "pullback"
        quality_points += pullback_score * 0.3
        reasons.append(f"pullback entry ({pullback_score:.2f})")

    # ── B. BREAKOUT QUALITY ──
    breakout_score = _score_breakout(is_long, close, candles, indicators, structure)
    if breakout_score > 0.6 and result.entry_type != "pullback":
        result.entry_type = "breakout"
        quality_points += breakout_score * 0.25
        reasons.append(f"breakout ({breakout_score:.2f})")

    # ── C. RETEST ENTRY ──
    if structure and structure.near_key_level and structure.bos:
        retest_score = 0.7
        if result.entry_type == "momentum":
            result.entry_type = "retest"
        quality_points += retest_score * 0.2
        reasons.append("retest after BOS")

    # ── D. EXHAUSTION CHECK ──
    exhaustion = _check_exhaustion(is_long, close, ema_20, atr, rsi, stoch_k, candles)
    if exhaustion > 0.6:
        quality_points -= exhaustion * 0.3
        reasons.append(f"exhaustion warning ({exhaustion:.2f})")
        if exhaustion > 0.8:
            result.entry_type = "poor"
            result.should_delay_entry = True

    # ── E. EXTENSION CHECK ──
    extension = _check_extension(is_long, close, ema_20, atr)
    if extension > 0.7:
        quality_points -= extension * 0.2
        reasons.append(f"overextended ({extension:.2f})")
        result.should_delay_entry = True

    # ── F. STRUCTURE ALIGNMENT ──
    if structure:
        if structure.structure_bias == direction:
            quality_points += 0.15
            reasons.append("structure aligned")
        elif structure.structure_bias != "NEUTRAL" and structure.structure_bias != direction:
            quality_points -= 0.10
            reasons.append("structure misaligned")

        if structure.failed_breakout:
            # Failed breakout in our direction is bad
            quality_points -= 0.10
            reasons.append("failed breakout caution")

        if structure.sweep_detected:
            # Sweeps can be reversal setups — good for counter direction
            quality_points += 0.05

    # ── G. TREND STRENGTH BONUS ──
    if adx > 30:
        quality_points += 0.05
    elif adx < 15:
        quality_points -= 0.05

    # ── COMPUTE FINAL SCORES ──
    base = 0.50
    result.entry_quality = round(max(0.0, min(1.0, base + quality_points)), 3)

    # Confidence adjustment: scale from quality
    # Good entry (0.7+) → up to +0.10 confidence
    # Poor entry (0.3-) → down to -0.10 confidence
    result.confidence_adjustment = round((result.entry_quality - 0.5) * 0.20, 3)

    # Size adjustment: good entries get full size, poor entries get reduced
    if result.entry_quality >= 0.65:
        result.size_adjustment = 1.0 + (result.entry_quality - 0.65) * 0.5  # Up to 1.175
    elif result.entry_quality < 0.35:
        result.size_adjustment = 0.6 + result.entry_quality  # Down to 0.6
    else:
        result.size_adjustment = 1.0

    result.size_adjustment = round(max(0.5, min(1.2, result.size_adjustment)), 3)
    result.reason = "; ".join(reasons) if reasons else "standard momentum entry"

    # Fallback type
    if result.entry_type == "momentum" and result.entry_quality < 0.35:
        result.entry_type = "poor"

    return result


def _score_pullback(is_long: bool, close: float, ema_20: float, ema_50: float,
                    atr: float, rsi: float, stoch_k: float) -> float:
    """Score pullback quality (0-1). High = good pullback entry opportunity."""
    if atr <= 0 or ema_20 <= 0:
        return 0.0

    score = 0.0

    if is_long:
        # Price near EMA20 or EMA50 from above (pulled back but not broken)
        dist_to_ema20 = (close - ema_20) / atr
        if 0 < dist_to_ema20 < 1.0:
            score += 0.4  # Near EMA20 — ideal pullback zone
        elif -0.5 < dist_to_ema20 <= 0:
            score += 0.3  # Slightly below EMA20 — deeper pullback
        elif dist_to_ema20 > 2.0:
            score -= 0.2  # Too far above — not a pullback

        # RSI pulled back but not oversold
        if 35 < rsi < 50:
            score += 0.3  # RSI cooled off
        elif rsi < 35:
            score += 0.15  # Oversold in uptrend — risky but can bounce

        # Stochastic oversold in uptrend
        if stoch_k < 30:
            score += 0.2
    else:
        # SHORT pullback: price near EMAs from below
        dist_to_ema20 = (ema_20 - close) / atr
        if 0 < dist_to_ema20 < 1.0:
            score += 0.4
        elif -0.5 < dist_to_ema20 <= 0:
            score += 0.3
        elif dist_to_ema20 > 2.0:
            score -= 0.2

        if 50 < rsi < 65:
            score += 0.3
        elif rsi > 65:
            score += 0.15

        if stoch_k > 70:
            score += 0.2

    return max(0.0, min(1.0, score))


def _score_breakout(is_long: bool, close: float, candles: list,
                    indicators: dict, structure: object) -> float:
    """Score breakout quality. High = legitimate breakout, low = likely fake."""
    bb_upper = indicators.get("bollinger_upper", close)
    bb_lower = indicators.get("bollinger_lower", close)
    bb_mid = indicators.get("bollinger_mid", close)
    atr = indicators.get("atr_14", close * 0.015)

    score = 0.0

    # Bollinger width compression (squeeze → breakout)
    if bb_upper > 0 and bb_lower > 0 and close > 0:
        bb_width = (bb_upper - bb_lower) / close
        if bb_width < 0.02:  # Tight squeeze
            score += 0.3
        elif bb_width < 0.03:
            score += 0.15

    # Price breaking BB band
    if is_long and close > bb_upper:
        score += 0.2
    elif not is_long and close < bb_lower:
        score += 0.2

    # ATR expansion (volatility pickup)
    if len(candles) >= 5:
        recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
        prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]] if len(candles) >= 10 else recent_ranges
        if prior_ranges:
            avg_recent = np.mean(recent_ranges)
            avg_prior = np.mean(prior_ranges)
            if avg_recent > avg_prior * 1.3:
                score += 0.2  # Range expanding

    # Candle body vs wick (strong close = real breakout)
    if candles:
        c = candles[-1]
        body = abs(c["close"] - c["open"])
        total = c["high"] - c["low"]
        if total > 0:
            body_ratio = body / total
            if body_ratio > 0.65:
                score += 0.15  # Strong body
            elif body_ratio < 0.3:
                score -= 0.15  # Weak body, long wicks

    # Structure: BOS adds confidence
    if structure and structure.bos:
        score += 0.15

    return max(0.0, min(1.0, score))


def _check_exhaustion(is_long: bool, close: float, ema_20: float, atr: float,
                      rsi: float, stoch_k: float, candles: list) -> float:
    """Check exhaustion level (0-1). High = don't enter."""
    score = 0.0

    if is_long:
        if rsi > 75:
            score += 0.3
        if rsi > 80:
            score += 0.2
        if stoch_k > 85:
            score += 0.2
        # Consecutive up candles (momentum exhaustion)
        if len(candles) >= 5:
            up_count = sum(1 for c in candles[-5:] if c["close"] > c["open"])
            if up_count >= 4:
                score += 0.2
            if up_count >= 5:
                score += 0.1
    else:
        if rsi < 25:
            score += 0.3
        if rsi < 20:
            score += 0.2
        if stoch_k < 15:
            score += 0.2
        if len(candles) >= 5:
            down_count = sum(1 for c in candles[-5:] if c["close"] < c["open"])
            if down_count >= 4:
                score += 0.2
            if down_count >= 5:
                score += 0.1

    return min(1.0, score)


def _check_extension(is_long: bool, close: float, ema_20: float, atr: float) -> float:
    """Check if price is overextended from mean (0-1). High = too far."""
    if atr <= 0 or ema_20 <= 0:
        return 0.0

    dist = abs(close - ema_20) / atr

    if is_long:
        if close > ema_20 and dist > 2.5:
            return min(1.0, (dist - 2.5) / 2.0 + 0.5)
        elif close > ema_20 and dist > 1.5:
            return min(0.5, (dist - 1.5) / 2.0)
    else:
        if close < ema_20 and dist > 2.5:
            return min(1.0, (dist - 2.5) / 2.0 + 0.5)
        elif close < ema_20 and dist > 1.5:
            return min(0.5, (dist - 1.5) / 2.0)

    return 0.0
