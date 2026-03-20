"""
Bahamut v4 — Exit Intelligence Engine

Smart exit management to capture more MFE and reduce MAE:
- Break-even stop migration after sufficient favorable move
- ATR trailing stop
- Structure-based trailing (swing lows for longs, swing highs for shorts)
- Momentum degradation exit
- Time-based decay tightening
- Partial take-profit at intermediate targets
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class ExitDecision:
    move_to_breakeven: bool = False
    new_stop_loss: float = 0.0          # 0 = no change
    partial_take_profit: float = 0.0    # 0-1 fraction to close
    trail_active: bool = False
    trail_method: str = "none"          # atr / structure / none
    force_exit: bool = False
    reason: str = ""


def evaluate_exit(
    trade: dict,
    candle: dict,
    indicators: dict,
    candles_since_entry: list,
    structure: object = None,
    # Configurable parameters for tuning
    trail_atr_mult: float = 1.5,     # ATR multiplier for trailing stop distance
    breakeven_r: float = 1.0,         # R-multiple to trigger break-even
    trail_trigger_r: float = 1.5,     # R-multiple to activate trailing
    partial_r: float = 1.8,           # R-multiple for partial TP
    partial_frac: float = 0.30,       # Fraction to take off at partial
) -> ExitDecision:
    """
    Evaluate whether to modify stop, take partial, or force exit.
    
    trade: dict with entry_price, stop_loss, take_profit, direction, entry_time, etc.
    candle: current OHLCV candle
    indicators: from compute_indicators()
    candles_since_entry: all candles from entry to current
    structure: StructureResult (optional)
    """
    decision = ExitDecision()
    
    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp = trade["take_profit"]
    direction = trade["direction"]
    is_long = direction == "LONG"
    close = candle["close"]
    atr = indicators.get("atr_14", abs(entry - sl) / 2)
    bars_held = len(candles_since_entry)

    # Favorable and adverse excursion
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    
    if is_long:
        favorable = close - entry
        mfe = max(c["high"] for c in candles_since_entry) - entry if candles_since_entry else 0
    else:
        favorable = entry - close
        mfe = entry - min(c["low"] for c in candles_since_entry) if candles_since_entry else 0

    r_multiple = favorable / sl_dist if sl_dist > 0 else 0
    mfe_r = mfe / sl_dist if sl_dist > 0 else 0
    progress = favorable / tp_dist if tp_dist > 0 else 0

    # ── A. BREAK-EVEN LOGIC ──
    # Move to break-even after breakeven_r favorable
    if r_multiple >= breakeven_r and not _is_at_breakeven(trade, entry):
        be_price = entry + (atr * 0.1 if is_long else -atr * 0.1)  # Tiny buffer
        if is_long and be_price > sl:
            decision.move_to_breakeven = True
            decision.new_stop_loss = round(be_price, 8)
            decision.reason = f"BE at 1R (r={r_multiple:.1f})"
        elif not is_long and be_price < sl:
            decision.move_to_breakeven = True
            decision.new_stop_loss = round(be_price, 8)
            decision.reason = f"BE at 1R (r={r_multiple:.1f})"

    # ── B. PARTIAL TAKE-PROFIT ──
    if partial_frac > 0 and partial_r <= r_multiple < partial_r + 0.8 and mfe_r >= partial_r:
        decision.partial_take_profit = partial_frac
        decision.reason += f"; partial TP at {partial_r:.1f}R"

    # ── C. ATR TRAILING STOP ──
    if r_multiple >= trail_trigger_r:
        decision.trail_active = True
        decision.trail_method = "atr"
        trail_distance = atr * trail_atr_mult
        if is_long:
            trail_stop = close - trail_distance
            if trail_stop > sl and trail_stop > entry:
                decision.new_stop_loss = max(
                    decision.new_stop_loss, round(trail_stop, 8))
        else:
            trail_stop = close + trail_distance
            if trail_stop < sl and trail_stop < entry:
                decision.new_stop_loss = min(
                    decision.new_stop_loss, round(trail_stop, 8)) if decision.new_stop_loss > 0 else round(trail_stop, 8)

    # ── D. STRUCTURE TRAILING ──
    if structure and r_multiple >= 1.0:
        if is_long and structure.swing_lows:
            # Trail behind the most recent swing low
            recent_sl = max(structure.swing_lows[-2:]) if len(structure.swing_lows) >= 2 else structure.swing_lows[-1]
            buffer = atr * 0.2
            struct_stop = recent_sl - buffer
            if struct_stop > sl and struct_stop > entry:
                if decision.new_stop_loss == 0 or struct_stop > decision.new_stop_loss:
                    decision.new_stop_loss = round(struct_stop, 8)
                    decision.trail_method = "structure"
                    decision.trail_active = True

        elif not is_long and structure.swing_highs:
            recent_sh = min(structure.swing_highs[-2:]) if len(structure.swing_highs) >= 2 else structure.swing_highs[-1]
            buffer = atr * 0.2
            struct_stop = recent_sh + buffer
            if struct_stop < sl and struct_stop < entry:
                if decision.new_stop_loss == 0 or struct_stop < decision.new_stop_loss:
                    decision.new_stop_loss = round(struct_stop, 8)
                    decision.trail_method = "structure"
                    decision.trail_active = True

    # ── E. MOMENTUM DEGRADATION EXIT ──
    rsi = indicators.get("rsi_14", 50)
    macd_hist = indicators.get("macd_histogram", 0)

    if r_multiple >= 1.5:  # Only exit if already well in profit
        # Require STRONG evidence of momentum reversal
        momentum_fading = False
        if is_long:
            if rsi < 40 and macd_hist < 0:  # Stricter thresholds
                momentum_fading = True
            if structure and structure.choch:
                momentum_fading = True
        else:
            if rsi > 60 and macd_hist > 0:
                momentum_fading = True
            if structure and structure.choch:
                momentum_fading = True

        if momentum_fading and r_multiple >= 1.5:
            # Instead of force exit, tighten stop aggressively
            if is_long:
                tight = close - atr * 0.5
                if tight > sl:
                    decision.new_stop_loss = max(decision.new_stop_loss, round(tight, 8))
                    decision.trail_active = True
                    decision.reason += "; momentum fading — tightened stop"
            else:
                tight = close + atr * 0.5
                if tight < sl:
                    sn = decision.new_stop_loss
                    decision.new_stop_loss = min(sn, round(tight, 8)) if sn > 0 else round(tight, 8)
                    decision.trail_active = True
                    decision.reason += "; momentum fading — tightened stop"

    # ── F. TIME DECAY ──
    # Only mild tightening, NO force exit (audit proved force exit is net negative)
    max_hold = trade.get("max_hold", 12)
    time_fraction = bars_held / max(1, max_hold)

    if time_fraction > 0.85 and r_multiple < 0.2:
        # Very late in trade with almost no progress → tighten gently
        if is_long:
            tight_stop = close - atr * 1.0
            if tight_stop > sl:
                decision.new_stop_loss = max(decision.new_stop_loss, round(tight_stop, 8))
                decision.reason += "; late-hold tightening"
        else:
            tight_stop = close + atr * 1.0
            if tight_stop < sl:
                sn = decision.new_stop_loss
                decision.new_stop_loss = min(sn, round(tight_stop, 8)) if sn > 0 else round(tight_stop, 8)
                decision.reason += "; late-hold tightening"

    return decision


def _is_at_breakeven(trade: dict, entry: float) -> bool:
    """Check if stop is already at or above breakeven."""
    sl = trade["stop_loss"]
    if trade["direction"] == "LONG":
        return sl >= entry * 0.999
    else:
        return sl <= entry * 1.001
