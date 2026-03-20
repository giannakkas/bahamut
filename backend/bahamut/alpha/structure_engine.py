"""
Bahamut v4 — Market Structure Engine

Real price-action structure analysis:
- Swing high/low detection with configurable lookback
- Higher-high / lower-low sequence tracking
- Break of Structure (BOS) and Change of Character (CHOCH)
- Support/Resistance zone detection
- Failed breakout and liquidity sweep detection
"""
import numpy as np
from dataclasses import dataclass, field


@dataclass
class SwingPoint:
    index: int
    price: float
    type: str  # "high" or "low"


@dataclass
class StructureResult:
    # Swing state
    structure_bias: str = "NEUTRAL"       # LONG / SHORT / NEUTRAL
    trend_state: str = "range"            # trend / range / transition
    # Events
    bos: bool = False                     # Break of Structure
    choch: bool = False                   # Change of Character
    near_key_level: bool = False
    failed_breakout: bool = False
    sweep_detected: bool = False
    # Scores
    quality_score: float = 0.5            # 0-1 overall structure quality
    # Detail
    swing_highs: list = field(default_factory=list)
    swing_lows: list = field(default_factory=list)
    nearest_resistance: float = 0.0
    nearest_support: float = 0.0
    pullback_depth: float = 0.0           # 0-1, how deep current pullback is


def analyze_structure(candles: list, indicators: dict, lookback: int = 40) -> StructureResult:
    """
    Analyze market structure from recent candles.
    
    candles: list of OHLCV dicts (most recent at end)
    indicators: from compute_indicators
    lookback: how many candles to analyze for swings
    """
    result = StructureResult()
    if len(candles) < 15:
        return result

    recent = candles[-lookback:] if len(candles) >= lookback else candles
    highs = np.array([c.get("high", c["close"]) for c in recent])
    lows = np.array([c.get("low", c["close"]) for c in recent])
    closes = np.array([c["close"] for c in recent])
    close = closes[-1]

    # ── 1. SWING DETECTION (3-bar pivot) ──
    swing_highs = []
    swing_lows = []
    for i in range(2, len(highs) - 2):
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and \
           highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
            swing_highs.append(SwingPoint(index=i, price=float(highs[i]), type="high"))
        if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and \
           lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
            swing_lows.append(SwingPoint(index=i, price=float(lows[i]), type="low"))

    result.swing_highs = [s.price for s in swing_highs[-5:]]
    result.swing_lows = [s.price for s in swing_lows[-5:]]

    # ── 2. TREND STRUCTURE (HH/HL vs LH/LL) ──
    hh_count, hl_count, lh_count, ll_count = 0, 0, 0, 0

    if len(swing_highs) >= 2:
        for k in range(1, min(4, len(swing_highs))):
            if swing_highs[-k].price > swing_highs[-k-1].price if k < len(swing_highs) else False:
                hh_count += 1
            elif swing_highs[-k].price < swing_highs[-k-1].price if k < len(swing_highs) else False:
                lh_count += 1

    if len(swing_lows) >= 2:
        for k in range(1, min(4, len(swing_lows))):
            if swing_lows[-k].price > swing_lows[-k-1].price if k < len(swing_lows) else False:
                hl_count += 1
            elif swing_lows[-k].price < swing_lows[-k-1].price if k < len(swing_lows) else False:
                ll_count += 1

    bull_points = hh_count + hl_count
    bear_points = lh_count + ll_count

    if bull_points >= 2 and bull_points > bear_points:
        result.structure_bias = "LONG"
        result.trend_state = "trend"
    elif bear_points >= 2 and bear_points > bull_points:
        result.structure_bias = "SHORT"
        result.trend_state = "trend"
    elif bull_points > 0 and bear_points > 0:
        result.trend_state = "transition"
    else:
        result.trend_state = "range"

    # ── 3. BOS / CHOCH DETECTION ──
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        last_sh = swing_highs[-1].price
        prev_sh = swing_highs[-2].price
        last_sl = swing_lows[-1].price
        prev_sl = swing_lows[-2].price

        # BOS: continuation break
        if result.structure_bias == "LONG" and close > last_sh:
            result.bos = True
        elif result.structure_bias == "SHORT" and close < last_sl:
            result.bos = True

        # CHOCH: reversal break
        if result.structure_bias == "LONG" and close < last_sl:
            result.choch = True
        elif result.structure_bias == "SHORT" and close > last_sh:
            result.choch = True
        # Also detect from NEUTRAL
        if result.structure_bias == "NEUTRAL":
            if close > prev_sh and len(swing_highs) >= 2:
                result.bos = True
                result.structure_bias = "LONG"
            elif close < prev_sl and len(swing_lows) >= 2:
                result.bos = True
                result.structure_bias = "SHORT"

    # ── 4. SUPPORT / RESISTANCE ZONES ──
    if swing_highs:
        # Nearest resistance: closest swing high above current price
        resistances = [s.price for s in swing_highs if s.price > close]
        result.nearest_resistance = min(resistances) if resistances else (
            swing_highs[-1].price if swing_highs else close * 1.02)

    if swing_lows:
        # Nearest support: closest swing low below current price
        supports = [s.price for s in swing_lows if s.price < close]
        result.nearest_support = max(supports) if supports else (
            swing_lows[-1].price if swing_lows else close * 0.98)

    # Near key level check
    atr = indicators.get("atr_14", close * 0.015)
    if atr > 0:
        if result.nearest_resistance > 0 and (result.nearest_resistance - close) < atr * 0.5:
            result.near_key_level = True
        if result.nearest_support > 0 and (close - result.nearest_support) < atr * 0.5:
            result.near_key_level = True

    # ── 5. FAILED BREAKOUT DETECTION ──
    if len(recent) >= 3 and swing_highs and swing_lows:
        prev_candle = recent[-2]
        curr_candle = recent[-1]
        last_res = swing_highs[-1].price if swing_highs else close * 1.1
        last_sup = swing_lows[-1].price if swing_lows else close * 0.9

        # Failed bullish breakout: prev high exceeded resistance but closed below
        if prev_candle["high"] > last_res and curr_candle["close"] < last_res:
            result.failed_breakout = True

        # Failed bearish breakout: prev low breached support but closed above
        if prev_candle["low"] < last_sup and curr_candle["close"] > last_sup:
            result.failed_breakout = True

    # ── 6. LIQUIDITY SWEEP DETECTION ──
    if len(recent) >= 2 and swing_highs and swing_lows:
        curr = recent[-1]
        body_top = max(curr["open"], curr["close"])
        body_bot = min(curr["open"], curr["close"])
        upper_wick = curr["high"] - body_top
        lower_wick = body_bot - curr["low"]
        body_size = body_top - body_bot + 1e-10

        # Sweep above swing high: long wick above, close back below
        if swing_highs and curr["high"] > swing_highs[-1].price and \
           curr["close"] < swing_highs[-1].price and upper_wick > body_size * 1.5:
            result.sweep_detected = True

        # Sweep below swing low: long wick below, close back above
        if swing_lows and curr["low"] < swing_lows[-1].price and \
           curr["close"] > swing_lows[-1].price and lower_wick > body_size * 1.5:
            result.sweep_detected = True

    # ── 7. PULLBACK DEPTH ──
    ema_20 = indicators.get("ema_20", close)
    ema_50 = indicators.get("ema_50", close)
    if atr > 0 and ema_20 > 0:
        if result.structure_bias == "LONG":
            # How far has price pulled back from recent high toward EMA support?
            recent_high = float(highs[-10:].max()) if len(highs) >= 10 else close
            pullback = (recent_high - close) / atr if atr > 0 else 0
            result.pullback_depth = min(1.0, max(0.0, pullback / 3.0))
        elif result.structure_bias == "SHORT":
            recent_low = float(lows[-10:].min()) if len(lows) >= 10 else close
            pullback = (close - recent_low) / atr if atr > 0 else 0
            result.pullback_depth = min(1.0, max(0.0, pullback / 3.0))

    # ── 8. QUALITY SCORE ──
    q = 0.5
    if result.trend_state == "trend":
        q += 0.15
    if result.bos:
        q += 0.10
    if result.choch:
        q -= 0.10  # Reversal signal — uncertain
    if result.failed_breakout:
        q -= 0.15
    if result.sweep_detected:
        q += 0.05  # Sweeps can be entry opportunities
    if result.near_key_level:
        q += 0.05
    result.quality_score = round(max(0.0, min(1.0, q)), 3)

    return result
