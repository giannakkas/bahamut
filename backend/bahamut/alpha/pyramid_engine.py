"""
Bahamut v6 — Pyramid Engine

Add to winning positions when trend confirms continuation.
NEVER add to losers. NEVER exceed max layered risk.

Three add-on types:
  A. Breakout continuation: price consolidates then breaks new high
  B. Pullback-in-trend: profitable trade, price pulls back to EMA, stabilizes
  C. Retest: price breaks swing high, retests, holds above

Position sizing:
  Layer 0 (initial): 1.0x risk
  Layer 1 (first add): 0.5x risk
  Layer 2 (second add): 0.25x risk
  Max total: 1.75x risk budget
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class PyramidSignal:
    should_add: bool = False
    add_type: str = "none"          # breakout / pullback / retest
    quality: float = 0.0
    size_fraction: float = 0.0     # Fraction of initial risk (0.5 or 0.25)
    stop_level: float = 0.0
    reason: str = ""


@dataclass
class LayerState:
    current_layers: int = 1
    max_layers: int = 3
    total_risk_used: float = 1.0   # 1.0 = initial only
    can_add: bool = True


def check_pyramid(
    trade_entry: float,
    trade_direction: str,
    current_price: float,
    current_layers: int,
    indicators: dict,
    candles: list,
    max_layers: int = 3,
) -> PyramidSignal:
    """
    Check if conditions warrant adding to an existing winning position.

    trade_entry: original entry price
    trade_direction: "LONG" or "SHORT"
    current_price: latest close
    current_layers: how many layers already open (1 = initial only)
    indicators: current indicators
    candles: recent 20-30 candles
    """
    sig = PyramidSignal()

    if current_layers >= max_layers:
        return sig

    if trade_direction != "LONG":
        return sig  # v5/v6 is long-only in bull regime

    # Must be in profit
    if current_price <= trade_entry:
        return sig

    atr = indicators.get("atr_14", current_price * 0.02)
    ema_20 = indicators.get("ema_20", current_price)
    ema_50 = indicators.get("ema_50", current_price)
    ema_200 = indicators.get("ema_200", current_price)
    rsi = indicators.get("rsi_14", 50)

    # Still in bull regime
    if current_price <= ema_200:
        return sig

    profit_pct = (current_price - trade_entry) / trade_entry
    profit_atr = (current_price - trade_entry) / atr if atr > 0 else 0

    # Determine size fraction
    if current_layers == 1:
        size_frac = 0.5
    else:
        size_frac = 0.25

    if len(candles) < 10:
        return sig

    # ── A. BREAKOUT CONTINUATION ──
    # Price made new high in last 5 bars, after consolidating
    highs_recent = [c["high"] for c in candles[-10:]]
    highs_prior = [c["high"] for c in candles[-20:-10]] if len(candles) >= 20 else highs_recent

    if highs_recent and highs_prior:
        recent_max = max(highs_recent[-3:])
        prior_max = max(highs_prior)

        # New high + price was consolidating (range narrowing)
        if recent_max > prior_max and profit_atr >= 1.5:
            recent_ranges = [c["high"] - c["low"] for c in candles[-5:]]
            prior_ranges = [c["high"] - c["low"] for c in candles[-10:-5]] if len(candles) >= 10 else recent_ranges

            # Consolidation: recent ranges smaller than prior
            if np.mean(recent_ranges) < np.mean(prior_ranges) * 1.2:
                sig.should_add = True
                sig.add_type = "breakout"
                sig.quality = min(1.0, 0.5 + profit_atr * 0.1)
                sig.size_fraction = size_frac
                sig.stop_level = ema_20 - atr * 0.5
                sig.reason = f"breakout continuation at +{profit_atr:.1f}R"
                return sig

    # ── B. PULLBACK-IN-TREND ──
    # Price near EMA20 in an uptrend, RSI has cooled
    dist_ema20 = (current_price - ema_20) / atr if atr > 0 else 0

    if -0.5 <= dist_ema20 <= 0.5 and ema_20 > ema_50 and profit_atr >= 1.0:
        if 35 <= rsi <= 55:
            # Bullish close after touching EMA zone
            curr = candles[-1]
            if curr["close"] > curr["open"]:
                sig.should_add = True
                sig.add_type = "pullback"
                sig.quality = min(1.0, 0.5 + (55 - rsi) * 0.01)
                sig.size_fraction = size_frac
                sig.stop_level = min(ema_50 - atr * 0.3, current_price - atr * 2)
                sig.reason = f"pullback to EMA20 at +{profit_atr:.1f}R, RSI={rsi:.0f}"
                return sig

    # ── C. RETEST ──
    # Price broke a recent swing high, now retesting it from above
    if len(candles) >= 15:
        # Find recent swing highs
        swing_highs = []
        for j in range(2, min(len(candles) - 2, 15)):
            h = candles[-(j+1)]
            if h["high"] > candles[-(j)]["high"] and h["high"] > candles[-(j+2)]["high"]:
                swing_highs.append(h["high"])

        if swing_highs and profit_atr >= 1.5:
            nearest_sh = max(sh for sh in swing_highs if sh < current_price * 1.02) \
                if any(sh < current_price * 1.02 for sh in swing_highs) else None

            if nearest_sh and abs(current_price - nearest_sh) < atr * 0.8:
                curr = candles[-1]
                if curr["close"] > nearest_sh and curr["close"] > curr["open"]:
                    sig.should_add = True
                    sig.add_type = "retest"
                    sig.quality = min(1.0, 0.6 + profit_atr * 0.05)
                    sig.size_fraction = size_frac
                    sig.stop_level = nearest_sh - atr * 0.5
                    sig.reason = f"retest of swing high ${nearest_sh:,.0f}"
                    return sig

    return sig


def get_layer_state(layers: int, max_layers: int = 3) -> LayerState:
    """Get current position layering state."""
    risk_map = {1: 1.0, 2: 1.5, 3: 1.75}
    return LayerState(
        current_layers=layers,
        max_layers=max_layers,
        total_risk_used=risk_map.get(layers, 1.75),
        can_add=layers < max_layers,
    )
