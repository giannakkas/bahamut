"""
Bahamut v5 — Regime Filter

Simple but critical: only trade in the direction of the dominant trend.
BTC is a structural bull asset. Shorting it in a bull regime is negative EV.

Rules:
  price > EMA200 → BULL → LONG only
  price < EMA200 → BEAR → SHORT only
  near EMA200 (within 1 ATR) → NEUTRAL → no trade

This single rule eliminates the #1 source of losses found in v4.1 audit:
141 short trades in a bull market losing $50K.
"""


def classify_regime(close: float, ema_200: float, atr: float) -> str:
    """Classify market regime from price position relative to EMA200."""
    if ema_200 <= 0 or atr <= 0:
        return "NEUTRAL"

    distance = (close - ema_200) / atr

    if distance > 1.0:
        return "BULL"
    elif distance < -1.0:
        return "BEAR"
    else:
        return "NEUTRAL"


def is_trade_allowed(direction: str, regime: str) -> bool:
    """Check if a trade direction is allowed in the current regime."""
    if regime == "BULL":
        return direction == "LONG"
    elif regime == "BEAR":
        return direction == "SHORT"
    else:
        return False  # No trading in NEUTRAL (transition zone)
