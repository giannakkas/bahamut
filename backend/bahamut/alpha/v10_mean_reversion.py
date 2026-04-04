"""
Bahamut v10 — Mean Reversion in Range Regimes

Hypothesis: "In range-bound markets, oversold conditions revert to the mean."

The edge: when price is stretched below its short-term mean (EMA20) in a RANGE
regime, with RSI confirmation and a bounce candle, price tends to snap back
toward the mean. This is the OPPOSITE of v5/v9 — it buys weakness, not strength.

When v10 fires vs others:
  v5  fires DURING trends  (after EMAs align — lagging momentum)
  v9  fires at the START of moves  (price exceeds recent highs — structural)
  v10 fires DURING ranges  (price dips below mean — counter-trend bounce)

These three together cover all market regimes:
  TREND  → v5 (ride momentum)
  RANGE  → v10 (buy dips to mean)
  BREAKOUT → v9 (catch the new move)

Key risk controls:
  - ONLY fires in RANGE regime (never trends or crashes)
  - Tight stops: max(1.5*ATR, 3.5% of entry)
  - Short hold: 10 bars max (~40 hours on 4H)
  - Requires bounce confirmation (not catching falling knives)
"""
import numpy as np
from dataclasses import dataclass
from bahamut.strategies.base import Signal


@dataclass
class MeanReversionSignal:
    """Internal signal object before conversion to system Signal."""
    valid: bool = False
    direction: str = "NONE"
    entry_type: str = "mean_reversion"
    confidence: float = 0.0
    reason: str = ""
    distance_from_mean_pct: float = 0.0
    rsi: float = 50.0
    target_price: float = 0.0


def detect_mean_reversion(
    candles: list,
    indicators: dict,
    prev_indicators: dict | None = None,
    regime: str = "RANGE",
    # ── Tunable parameters ──
    min_ema_distance_pct: float = 0.02,   # 2% below EMA20
    bb_tolerance: float = 1.005,           # within 0.5% of lower band
    rsi_threshold: float = 35.0,           # RSI ≤ 35
    rsi_cross_level: float = 30.0,         # OR RSI crossed up from < 30
    min_candles: int = 25,                 # minimum data requirement
) -> MeanReversionSignal:
    """
    Detect a mean reversion setup in range-bound markets.

    Entry logic (ALL must pass):
      1. Regime is RANGE
      2. Price stretched below EMA20 by at least min_ema_distance_pct
      3. Price near or below lower Bollinger Band
      4. RSI ≤ threshold OR RSI crossed up from below cross_level
      5. Bounce confirmation: current close > previous close OR close > lower band

    Returns MeanReversionSignal with validity and metadata.
    """
    sig = MeanReversionSignal()

    # ── Minimum data check ──
    if not candles or len(candles) < min_candles:
        sig.reason = f"insufficient data ({len(candles) if candles else 0} < {min_candles})"
        return sig

    # ── Extract indicators ──
    close = indicators.get("close", 0)
    ema_20 = indicators.get("ema_20", 0)
    bb_lower = indicators.get("bollinger_lower", 0)
    bb_mid = indicators.get("bollinger_mid", 0)
    rsi = indicators.get("rsi_14", 50)
    atr = indicators.get("atr_14", 0)

    if close <= 0 or ema_20 <= 0 or bb_lower <= 0 or atr <= 0:
        sig.reason = "missing indicators"
        return sig

    # ═══════════════════════════════════════════
    # CONDITION 1: RANGE regime only
    # ═══════════════════════════════════════════
    if regime not in ("RANGE",):
        sig.reason = f"wrong regime: {regime} (need RANGE)"
        return sig

    # ═══════════════════════════════════════════
    # CONDITION 2: Price stretched below EMA20
    # ═══════════════════════════════════════════
    distance_from_ema = (ema_20 - close) / ema_20
    if distance_from_ema < min_ema_distance_pct:
        sig.reason = f"not stretched enough: {distance_from_ema:.3f} < {min_ema_distance_pct}"
        return sig

    # ═══════════════════════════════════════════
    # CONDITION 3: Price near or below lower Bollinger Band
    # ═══════════════════════════════════════════
    bb_condition = close <= bb_lower * bb_tolerance
    if not bb_condition:
        sig.reason = f"above lower band: close {close:.2f} > band {bb_lower * bb_tolerance:.2f}"
        return sig

    # ═══════════════════════════════════════════
    # CONDITION 4: RSI oversold or crossing up
    # ═══════════════════════════════════════════
    prev_rsi = prev_indicators.get("rsi_14", 50) if prev_indicators else 50
    rsi_oversold = rsi <= rsi_threshold
    rsi_crossed_up = prev_rsi < rsi_cross_level and rsi >= rsi_cross_level

    if not rsi_oversold and not rsi_crossed_up:
        sig.reason = f"RSI not oversold: {rsi:.1f} (need ≤{rsi_threshold} or cross up from <{rsi_cross_level})"
        return sig

    # ═══════════════════════════════════════════
    # CONDITION 5: Bounce confirmation
    # ═══════════════════════════════════════════
    prev_close = candles[-2]["close"] if len(candles) >= 2 else 0
    bounce_higher = close > prev_close
    reclaimed_band = close > bb_lower

    if not bounce_higher and not reclaimed_band:
        sig.reason = f"no bounce: close {close:.2f} ≤ prev {prev_close:.2f} and below band {bb_lower:.2f}"
        return sig

    # ═══════════════════════════════════════════
    # ALL CONDITIONS MET — compute quality score
    # ═══════════════════════════════════════════
    quality = 0.5

    # Deeper stretch = higher conviction (capped)
    stretch_bonus = min(0.15, (distance_from_ema - min_ema_distance_pct) * 5)
    quality += stretch_bonus

    # Lower RSI = more oversold = higher conviction
    if rsi <= 25:
        quality += 0.15
    elif rsi <= 30:
        quality += 0.10
    elif rsi <= 35:
        quality += 0.05

    # RSI divergence bonus: RSI crossed up from oversold
    if rsi_crossed_up:
        quality += 0.10

    # Strong bounce candle (close near high of bar)
    bar_range = candles[-1].get("high", close) - candles[-1].get("low", close)
    if bar_range > 0:
        close_position = (close - candles[-1].get("low", close)) / bar_range
        if close_position > 0.7:  # Close in upper 30% of bar
            quality += 0.05

    # Volume expansion on bounce (sign of real demand)
    vol = candles[-1].get("volume", 0)
    prev_vol = candles[-2].get("volume", 0) if len(candles) >= 2 else 0
    if vol > 0 and prev_vol > 0 and vol > prev_vol * 1.3:
        quality += 0.05

    quality = round(min(1.0, quality), 3)

    # ── Build reason string ──
    reasons = []
    reasons.append(f"RANGE mean reversion: {distance_from_ema*100:.1f}% below EMA20")
    if rsi_crossed_up:
        reasons.append(f"RSI crossed up from {prev_rsi:.0f} to {rsi:.0f}")
    else:
        reasons.append(f"RSI oversold at {rsi:.0f}")
    if bounce_higher:
        reasons.append("bounce confirmed (close > prev close)")
    if reclaimed_band:
        reasons.append("reclaimed lower band")

    sig.valid = True
    sig.direction = "LONG"
    sig.confidence = quality
    sig.distance_from_mean_pct = round(distance_from_ema * 100, 2)
    sig.rsi = round(rsi, 1)
    sig.target_price = round(bb_mid, 6)  # Target = Bollinger midline (≈ EMA20)
    sig.reason = " · ".join(reasons)

    return sig


def detect_mean_reversion_short(
    candles: list,
    indicators: dict,
    prev_indicators: dict | None = None,
    regime: str = "RANGE",
    min_ema_distance_pct: float = 0.02,
    bb_tolerance: float = 0.995,
    rsi_threshold: float = 65.0,
    rsi_cross_level: float = 70.0,
    min_candles: int = 25,
) -> MeanReversionSignal:
    """Detect a mean reversion SHORT setup — mirror of LONG detection.

    Entry logic (ALL must pass):
      1. Regime is RANGE
      2. Price stretched ABOVE EMA20 by at least min_ema_distance_pct
      3. Price near or above upper Bollinger Band
      4. RSI >= threshold OR RSI crossed down from above cross_level
      5. Rejection confirmation: current close < previous close OR close < upper band
    """
    sig = MeanReversionSignal()

    if not candles or len(candles) < min_candles:
        sig.reason = f"insufficient data ({len(candles) if candles else 0} < {min_candles})"
        return sig

    close = indicators.get("close", 0)
    ema_20 = indicators.get("ema_20", 0)
    bb_upper = indicators.get("bollinger_upper", 0)
    bb_mid = indicators.get("bollinger_mid", 0)
    rsi = indicators.get("rsi_14", 50)
    atr = indicators.get("atr_14", 0)

    if close <= 0 or ema_20 <= 0 or bb_upper <= 0 or atr <= 0:
        sig.reason = "missing indicators"
        return sig

    if regime not in ("RANGE",):
        sig.reason = f"wrong regime: {regime} (need RANGE)"
        return sig

    # Price stretched ABOVE EMA20
    distance_from_ema = (close - ema_20) / ema_20
    if distance_from_ema < min_ema_distance_pct:
        sig.reason = f"not stretched enough above: {distance_from_ema:.3f} < {min_ema_distance_pct}"
        return sig

    # Price near or above upper Bollinger Band
    bb_condition = close >= bb_upper * bb_tolerance
    if not bb_condition:
        sig.reason = f"below upper band: close {close:.2f} < band {bb_upper * bb_tolerance:.2f}"
        return sig

    # RSI overbought or crossing down
    prev_rsi = prev_indicators.get("rsi_14", 50) if prev_indicators else 50
    rsi_overbought = rsi >= rsi_threshold
    rsi_crossed_down = prev_rsi > rsi_cross_level and rsi <= rsi_cross_level

    if not rsi_overbought and not rsi_crossed_down:
        sig.reason = f"RSI not overbought: {rsi:.1f} (need >={rsi_threshold} or cross down from >{rsi_cross_level})"
        return sig

    # Rejection confirmation
    prev_close = candles[-2]["close"] if len(candles) >= 2 else close
    rejection_lower = close < prev_close
    below_band = close < bb_upper

    if not rejection_lower and not below_band:
        sig.reason = f"no rejection: close {close:.2f} >= prev {prev_close:.2f} and above band {bb_upper:.2f}"
        return sig

    # Quality score
    quality = 0.5
    stretch_bonus = min(0.15, (distance_from_ema - min_ema_distance_pct) * 5)
    quality += stretch_bonus

    if rsi >= 75:
        quality += 0.15
    elif rsi >= 70:
        quality += 0.10
    elif rsi >= 65:
        quality += 0.05

    if rsi_crossed_down:
        quality += 0.10

    bar_range = candles[-1].get("high", close) - candles[-1].get("low", close)
    if bar_range > 0:
        close_position = (close - candles[-1].get("low", close)) / bar_range
        if close_position < 0.3:
            quality += 0.05

    quality = round(min(1.0, quality), 3)

    reasons = []
    reasons.append(f"RANGE mean reversion SHORT: {distance_from_ema*100:.1f}% above EMA20")
    if rsi_crossed_down:
        reasons.append(f"RSI crossed down from {prev_rsi:.0f} to {rsi:.0f}")
    else:
        reasons.append(f"RSI overbought at {rsi:.0f}")
    if rejection_lower:
        reasons.append("rejection confirmed (close < prev close)")

    sig.valid = True
    sig.direction = "SHORT"
    sig.confidence = quality
    sig.distance_from_mean_pct = round(distance_from_ema * 100, 2)
    sig.rsi = round(rsi, 1)
    sig.target_price = round(bb_mid, 6)
    sig.reason = " · ".join(reasons)

    return sig


def detect_crash_short(
    candles: list,
    indicators: dict,
    prev_indicators: dict | None = None,
    min_candles: int = 25,
) -> MeanReversionSignal:
    """Detect a SHORT setup during CRASH — sell bear market rallies.

    Entry logic:
      1. Price below EMA200 (confirms downtrend)
      2. Price rallied within 6% of EMA20 (or above it)
      3. RSI recovered above 40 (rally happened)
      4. Rejection: close < prev close OR bearish candle
    """
    sig = MeanReversionSignal()

    if not candles or len(candles) < min_candles:
        sig.reason = "insufficient data"
        return sig

    close = indicators.get("close", 0)
    ema_20 = indicators.get("ema_20", 0)
    ema_200 = indicators.get("ema_200", 0)
    bb_mid = indicators.get("bollinger_mid", ema_20)
    rsi = indicators.get("rsi_14", 50)

    if close <= 0 or ema_20 <= 0 or ema_200 <= 0:
        sig.reason = "missing indicators"
        return sig

    if close >= ema_200:
        sig.reason = "price above EMA200 — not a crash"
        return sig

    dist_to_ema20 = (ema_20 - close) / ema_20
    if dist_to_ema20 > 0.06:
        sig.reason = f"price still far below EMA20: {dist_to_ema20*100:.1f}%"
        return sig

    if rsi < 35:
        sig.reason = f"RSI too low ({rsi:.0f}) — still oversold"
        return sig

    prev_close = candles[-2]["close"] if len(candles) >= 2 else close
    bar_open = candles[-1].get("open", close)
    rejection_lower = close < prev_close
    bearish_candle = close < bar_open

    if not rejection_lower and not bearish_candle:
        sig.reason = "no rejection — price still rallying"
        return sig

    quality = 0.50
    # Closer to EMA20 = better entry
    if dist_to_ema20 <= 0.01:
        quality += 0.15  # Within 1% — right at resistance
    elif dist_to_ema20 <= 0.02:
        quality += 0.12  # Within 2%
    elif dist_to_ema20 <= 0.03:
        quality += 0.08  # Within 3%
    elif dist_to_ema20 <= 0.04:
        quality += 0.05  # Within 4%
    # 4-6% = base quality only (lower conviction)
    if close > ema_20:
        quality += 0.15  # Above EMA20 — best entry
    if 35 <= rsi <= 55:
        quality += 0.10
    elif rsi > 55:
        quality += 0.05
    if rejection_lower and bearish_candle:
        quality += 0.05

    quality = round(min(1.0, quality), 3)

    reasons = [
        f"CRASH short: bear rally to EMA20 (dist {dist_to_ema20*100:.1f}%)",
        f"RSI recovered to {rsi:.0f}",
    ]
    if rejection_lower:
        reasons.append("rejection (close < prev)")
    if bearish_candle:
        reasons.append("bearish candle")

    sig.valid = True
    sig.direction = "SHORT"
    sig.confidence = quality
    sig.distance_from_mean_pct = round(dist_to_ema20 * 100, 2)
    sig.rsi = round(rsi, 1)
    sig.target_price = round(bb_mid * 0.97, 6)
    sig.reason = " · ".join(reasons)

    return sig


class V10MeanReversion:
    """Strategy wrapper for the execution framework.

    Integrates with the same interface as V5Base, V5Tuned, V9Breakout:
      evaluate(candles, indicators, prev_indicators, asset) → Signal | None
    """

    def __init__(self):
        self.name = "v10_mean_reversion"
        self.max_hold = 10          # ~40 hours on 4H bars (short-duration trades)
        self.risk_pct = 0.015       # 1.5% risk per trade (slightly lower than trend strategies)

    def evaluate(self, candles, indicators, prev_indicators=None, asset="BTCUSD"):
        """Evaluate for mean reversion setup — LONG, SHORT, and CRASH SHORT.

        LONG:  oversold in RANGE → bounce to mean
        SHORT: overbought in RANGE → rejection to mean
        CRASH SHORT: bear rally in CRASH → sell into resistance
        """
        regime = indicators.get("_regime", "UNKNOWN")

        # Try LONG first (oversold → bounce) — only in RANGE
        sig = detect_mean_reversion(candles, indicators, prev_indicators, regime=regime)

        # If no LONG, try SHORT (overbought → rejection) — only in RANGE
        if not sig.valid:
            sig = detect_mean_reversion_short(candles, indicators, prev_indicators, regime=regime)

        # If no RANGE signal, try CRASH SHORT (bear rally → sell resistance)
        if not sig.valid and regime == "CRASH":
            sig = detect_crash_short(candles, indicators, prev_indicators)

        if not sig.valid:
            return None

        # ── Dynamic SL/TP based on ATR and timeframe ──
        close = indicators.get("close", 0)
        atr = indicators.get("atr_14", 0)
        ema_20 = indicators.get("ema_20", close)
        bb_mid = indicators.get("bollinger_mid", ema_20)
        interval = indicators.get("_interval", "4h")

        # Tighter floors for faster timeframes (15m crypto)
        if interval in ("15m", "5m", "1m"):
            sl_floor = 0.008     # 0.8% min SL (was 3.5%)
            sl_cap = 0.03        # 3% max SL (was 8%)
            tp_floor = 0.005     # 0.5% min TP (was 2%)
            tp_cap = 0.04        # 4% max TP (was 8%)
            atr_mult = 2.0       # 2×ATR for stop (was 1.5×)
        else:
            sl_floor = 0.035     # 3.5% min SL
            sl_cap = 0.08        # 8% max SL
            tp_floor = 0.02      # 2% min TP
            tp_cap = 0.08        # 8% max TP
            atr_mult = 1.5       # 1.5×ATR for stop

        # Stop loss: max(atr_mult * ATR, floor)
        atr_stop = (atr_mult * atr) / close if close > 0 else sl_floor
        sl_pct = max(atr_stop, sl_floor)
        sl_pct = min(sl_pct, sl_cap)

        # Take profit: distance to mean (EMA20 / Bollinger midline)
        if sig.direction == "LONG":
            target = max(bb_mid, ema_20)
            tp_pct = (target - close) / close if close > 0 else tp_floor
        else:  # SHORT
            target = min(bb_mid, ema_20)
            tp_pct = (close - target) / close if close > 0 else tp_floor

        tp_pct = max(tp_pct, tp_floor)
        tp_pct = min(tp_pct, tp_cap)

        bar_ts = candles[-1].get("datetime", "") if candles else ""

        # Forex moves slowly — extend hold time
        asset_class = indicators.get("_asset_class", "")
        hold = 30 if asset_class == "forex" else self.max_hold

        return Signal(
            strategy=self.name,
            asset=asset,
            direction=sig.direction,
            sl_pct=round(sl_pct, 4),
            tp_pct=round(tp_pct, 4),
            max_hold_bars=hold,
            quality=sig.confidence,
            reason=sig.reason,
            signal_id=f"{self.name}:{asset}:{bar_ts}",
        )


# ═══════════════════════════════════════════════════════
# CANDIDATE SCORING (for Training Operations dashboard)
# ═══════════════════════════════════════════════════════

def score_mean_reversion(
    asset: str,
    asset_class: str,
    candles: list,
    indicators: dict,
    prev_indicators: dict | None = None,
    regime: str = "RANGE",
) -> "Candidate | None":
    """Score proximity to v10 mean reversion trigger.

    Returns a Candidate with score 0-100 representing how close
    the asset is to triggering a mean reversion entry.

    Scoring breakdown (100 total):
      - Regime alignment:     20pts (RANGE = full, others = 0)
      - EMA distance:         25pts (further below = higher)
      - Bollinger proximity:  20pts (closer to lower band = higher)
      - RSI oversold:         20pts (lower RSI = higher)
      - Bounce confirmation:  15pts (close > prev close, volume)
    """
    # Lazy import to avoid circular dependency
    from bahamut.training.candidates import Candidate

    close = indicators.get("close", 0)
    ema_20 = indicators.get("ema_20", 0)
    bb_lower = indicators.get("bollinger_lower", 0)
    bb_mid = indicators.get("bollinger_mid", 0)
    bb_upper = indicators.get("bollinger_upper", 0)
    rsi = indicators.get("rsi_14", 50)
    atr = indicators.get("atr_14", 0)

    if close <= 0 or ema_20 <= 0 or atr <= 0 or len(candles) < 25:
        return None

    reasons = []
    missing = []
    bd = {"regime": 0, "ema_distance": 0, "bollinger": 0, "rsi": 0, "bounce": 0}

    # ── 1. Regime (20 pts) ──
    if regime == "RANGE":
        bd["regime"] = 20
        reasons.append("RANGE regime — mean reversion eligible")
    else:
        bd["regime"] = 0
        missing.append(f"Need RANGE regime (currently {regime})")

    # ── 2. EMA distance (25 pts) ──
    ema_dist = (ema_20 - close) / ema_20 if ema_20 > 0 else 0
    ema_dist_pct = ema_dist * 100

    if ema_dist >= 0.04:       # 4%+ below → full score
        bd["ema_distance"] = 25
        reasons.append(f"Price {ema_dist_pct:.1f}% below EMA20 (deeply oversold)")
    elif ema_dist >= 0.02:     # 2-4% below → good
        bd["ema_distance"] = int(15 + (ema_dist - 0.02) / 0.02 * 10)
        reasons.append(f"Price {ema_dist_pct:.1f}% below EMA20")
    elif ema_dist >= 0.01:     # 1-2% below → approaching
        bd["ema_distance"] = int(5 + (ema_dist - 0.01) / 0.01 * 10)
        missing.append(f"Need {(0.02 - ema_dist)*100:.1f}% more below EMA20")
    elif ema_dist > 0:         # slightly below
        bd["ema_distance"] = int(ema_dist / 0.01 * 5)
        missing.append(f"Price only {ema_dist_pct:.1f}% below EMA20 (need ≥2%)")
    else:
        bd["ema_distance"] = 0
        missing.append(f"Price {abs(ema_dist_pct):.1f}% ABOVE EMA20 (need below)")

    # ── 3. Bollinger Band proximity (20 pts) ──
    if bb_lower > 0 and bb_upper > 0:
        bb_width = bb_upper - bb_lower
        bb_position = (close - bb_lower) / bb_width if bb_width > 0 else 0.5

        if close <= bb_lower:
            bd["bollinger"] = 20
            reasons.append(f"Below lower Bollinger Band")
        elif close <= bb_lower * 1.005:
            bd["bollinger"] = 18
            reasons.append(f"At lower Bollinger Band")
        elif bb_position < 0.15:
            bd["bollinger"] = int(10 + (0.15 - bb_position) / 0.15 * 8)
            reasons.append(f"Near lower band ({bb_position*100:.0f}% of range)")
        elif bb_position < 0.30:
            bd["bollinger"] = int(bb_position / 0.30 * 10)
            missing.append(f"Price at {bb_position*100:.0f}% of BB range (need <15%)")
        else:
            bd["bollinger"] = 0
            missing.append(f"Price at {bb_position*100:.0f}% of BB range (need near lower band)")

    # ── 4. RSI (20 pts) ──
    prev_rsi = prev_indicators.get("rsi_14", 50) if prev_indicators else 50
    rsi_crossed_up = prev_rsi < 30 and rsi >= 30

    if rsi <= 25:
        bd["rsi"] = 20
        reasons.append(f"RSI deeply oversold at {rsi:.0f}")
    elif rsi <= 30:
        bd["rsi"] = 17
        reasons.append(f"RSI oversold at {rsi:.0f}")
    elif rsi_crossed_up:
        bd["rsi"] = 16
        reasons.append(f"RSI crossed up from {prev_rsi:.0f} to {rsi:.0f}")
    elif rsi <= 35:
        bd["rsi"] = 12
        reasons.append(f"RSI approaching oversold at {rsi:.0f}")
    elif rsi <= 40:
        bd["rsi"] = 6
        missing.append(f"RSI at {rsi:.0f} (need ≤35)")
    else:
        bd["rsi"] = 0
        missing.append(f"RSI at {rsi:.0f} — not oversold (need ≤35)")

    # ── 5. Bounce confirmation (15 pts) ──
    prev_close = candles[-2]["close"] if len(candles) >= 2 else close
    bounce = close > prev_close
    reclaimed = close > bb_lower

    if bounce and reclaimed:
        bd["bounce"] = 15
        reasons.append("Bounce confirmed: close > prev + above lower band")
    elif bounce:
        bd["bounce"] = 10
        reasons.append("Partial bounce: close > prev close")
    elif reclaimed:
        bd["bounce"] = 8
        reasons.append("Reclaimed lower band")
    else:
        bd["bounce"] = 0
        missing.append("No bounce yet — close ≤ prev close and below band")

    # ── Compute total score ──
    score = sum(bd.values())
    score = max(0, min(100, score))

    # ── Build distance string ──
    dist_str = f"{ema_dist_pct:.1f}% below EMA20" if ema_dist > 0 else f"{abs(ema_dist_pct):.1f}% above EMA20"

    # ── EMA alignment for display ──
    ema_alignment = "bearish stack" if close < ema_20 else "bullish stack"

    return Candidate(
        asset=asset,
        asset_class=asset_class,
        strategy="v10_mean_reversion",
        direction="LONG",
        score=score,
        regime=regime,
        distance_to_trigger=dist_str,
        reasons=reasons,
        indicators={
            "rsi": round(rsi, 1),
            "ema_alignment": ema_alignment,
            "ema_20": round(ema_20, 6),
            "bb_lower": round(bb_lower, 6),
            "bb_mid": round(bb_mid, 6),
            "atr": round(atr, 6),
            "ema_distance_pct": round(ema_dist_pct, 2),
        },
        score_breakdown=bd,
        missing_conditions=missing,
        explanation=f"Mean reversion score {score}/100. "
                    + (f"Price {ema_dist_pct:.1f}% below EMA20, RSI {rsi:.0f}. " if ema_dist > 0 else "")
                    + ("READY to trigger." if score >= 80 else
                       "Approaching trigger." if score >= 50 else
                       "Conditions not met."),
    )
