"""
Bahamut v6 — Trend Capture Engine

Classify trade profit state to control exit behavior:
  EARLY_TREND: give maximum room, no tightening
  ESTABLISHED_TREND: allow trailing, protect some profit
  EXTENDED_TREND: tighten progressively

This is NOT a signal generator. It's a monetization layer
that prevents cutting strong trends too early.
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class TrendState:
    state: str = "EARLY_TREND"     # EARLY / ESTABLISHED / EXTENDED
    continuation_score: float = 0.5
    should_hold: bool = True
    tighten_stop: bool = False
    profit_lock_r: float = 0.0    # R-multiple to lock (0 = no lock)


def classify_trend(
    entry_price: float,
    current_price: float,
    sl_distance: float,
    indicators: dict,
    bars_held: int,
    candles_since_entry: list,
) -> TrendState:
    """
    Classify the profit state of an open winning trade.

    entry_price: original entry
    current_price: current close
    sl_distance: abs(entry - original_stop)
    indicators: current indicators
    bars_held: candles since entry
    candles_since_entry: candle list from entry to now
    """
    ts = TrendState()

    if sl_distance <= 0 or current_price <= entry_price:
        ts.state = "EARLY_TREND"
        ts.should_hold = True
        return ts

    r_multiple = (current_price - entry_price) / sl_distance
    ema_20 = indicators.get("ema_20", current_price)
    ema_50 = indicators.get("ema_50", current_price)
    atr = indicators.get("atr_14", current_price * 0.02)

    # ── STATE CLASSIFICATION ──
    if r_multiple < 1.5 or bars_held < 5:
        ts.state = "EARLY_TREND"
        ts.should_hold = True
        ts.tighten_stop = False
        # No profit lock in early trend
    elif r_multiple < 3.5:
        ts.state = "ESTABLISHED_TREND"
        ts.should_hold = True
        ts.tighten_stop = False  # Not yet — let it breathe
        # Lock some profit
        ts.profit_lock_r = max(0, r_multiple * 0.3)  # Lock 30% of current R
    else:
        ts.state = "EXTENDED_TREND"
        ts.should_hold = True  # Still hold, but tighten
        ts.tighten_stop = True
        ts.profit_lock_r = max(1.0, r_multiple * 0.5)  # Lock 50% of current R

    # ── CONTINUATION SCORE ──
    score = 0.5

    # Price above key EMAs
    if current_price > ema_20 > ema_50:
        score += 0.15
    elif current_price > ema_20:
        score += 0.05

    # Making new highs
    if candles_since_entry and len(candles_since_entry) >= 5:
        recent_high = max(c["high"] for c in candles_since_entry[-5:])
        all_high = max(c["high"] for c in candles_since_entry)
        if recent_high >= all_high * 0.99:
            score += 0.15  # Near or at new highs

    # Shallow pullbacks (healthy trend)
    if candles_since_entry and len(candles_since_entry) >= 3:
        recent_low = min(c["low"] for c in candles_since_entry[-3:])
        if atr > 0:
            pullback_depth = (current_price - recent_low) / atr
            if pullback_depth < 1.0:
                score += 0.1  # Shallow pullback — trend intact

    # Not exhausted
    rsi = indicators.get("rsi_14", 50)
    if rsi < 75:
        score += 0.05
    elif rsi > 85:
        score -= 0.15  # Very overbought — trend may be exhausting

    ts.continuation_score = round(min(1.0, max(0.0, score)), 3)

    # Override: if continuation is very weak, consider tightening even in established
    if ts.continuation_score < 0.3 and ts.state == "ESTABLISHED_TREND":
        ts.tighten_stop = True

    return ts


def compute_profit_lock_stop(
    entry_price: float,
    sl_distance: float,
    profit_lock_r: float,
) -> float:
    """Compute the stop level that locks a given R-multiple of profit."""
    if profit_lock_r <= 0 or sl_distance <= 0:
        return 0.0
    return entry_price + profit_lock_r * sl_distance
