"""
Bahamut v8 — Regime Detector

Classifies market into one of 3 regimes:
  TREND — price above EMA200, positive slope, trending behavior
  RANGE — price near EMA200, flat EMAs, oscillating
  CRASH — price below EMA200, elevated volatility, breakdown

Rules are deterministic, explainable, no future leakage.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class RegimeResult:
    regime: str = "RANGE"          # TREND / RANGE / CRASH
    confidence: float = 0.5
    reason: str = ""
    features: dict = None

    def __post_init__(self):
        if self.features is None:
            self.features = {}


def detect_regime(indicators: dict, candles: list = None) -> RegimeResult:
    """
    Detect current market regime from indicators.

    indicators: from compute_indicators() — needs close, ema_20, ema_50, ema_200, atr_14, adx_14
    candles: optional recent candles for slope calculation
    """
    close = indicators.get("close", 0)
    ema_50 = indicators.get("ema_50", 0)
    ema_200 = indicators.get("ema_200", 0)
    atr = indicators.get("atr_14", 0)
    adx = indicators.get("adx_14", 20)

    if close <= 0 or ema_200 <= 0:
        return RegimeResult(regime="RANGE", confidence=0.3, reason="insufficient data")

    # ── Core features ──
    dist_to_ema200_pct = (close - ema_200) / ema_200 * 100
    atr_pct = (atr / close * 100) if close > 0 else 0

    # EMA50 slope: compare current EMA50 to ~10 bars ago
    ema50_slope = 0.0
    if candles and len(candles) >= 12 and ema_50 > 0:
        # Approximate prior EMA50 from price history
        prior_closes = [c["close"] for c in candles[-12:-2]]
        if prior_closes:
            prior_avg = np.mean(prior_closes)
            ema50_slope = (ema_50 - prior_avg) / prior_avg * 100

    features = {
        "price_vs_ema200": round(dist_to_ema200_pct, 2),
        "ema50_slope": round(ema50_slope, 3),
        "atr_pct": round(atr_pct, 3),
        "distance_to_ema200_pct": round(abs(dist_to_ema200_pct), 2),
        "adx": round(adx, 1),
    }

    # ═══════════════════════════════════════════════════
    # CRASH: price well below EMA200 + elevated vol
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct < -5 and atr_pct > 2.5:
        confidence = min(1.0, 0.6 + abs(dist_to_ema200_pct) * 0.02 + atr_pct * 0.05)
        return RegimeResult(
            regime="CRASH",
            confidence=round(confidence, 3),
            reason=f"price {dist_to_ema200_pct:+.1f}% below EMA200, ATR {atr_pct:.1f}% (elevated)",
            features=features,
        )

    if dist_to_ema200_pct < -8:
        confidence = min(1.0, 0.5 + abs(dist_to_ema200_pct) * 0.03)
        return RegimeResult(
            regime="CRASH",
            confidence=round(confidence, 3),
            reason=f"price {dist_to_ema200_pct:+.1f}% below EMA200 (deep breakdown)",
            features=features,
        )

    # ═══════════════════════════════════════════════════
    # CRASH (soft): below EMA200 + negative slope = slow bleed
    # Catches crypto downtrends that don't spike in volatility
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct < -2 and ema50_slope < -0.15:
        confidence = min(1.0, 0.5 + abs(dist_to_ema200_pct) * 0.03 + abs(ema50_slope) * 0.1)
        return RegimeResult(
            regime="CRASH",
            confidence=round(confidence, 3),
            reason=f"price {dist_to_ema200_pct:+.1f}% below EMA200, slope {ema50_slope:+.2f}% (slow bleed)",
            features=features,
        )

    # ═══════════════════════════════════════════════════
    # TREND: price above EMA200, positive slope, trending
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct > 3 and ema50_slope > 0.1:
        confidence = min(1.0, 0.5 + dist_to_ema200_pct * 0.02 + ema50_slope * 0.1)
        if adx > 25:
            confidence = min(1.0, confidence + 0.1)
        return RegimeResult(
            regime="TREND",
            confidence=round(confidence, 3),
            reason=f"price +{dist_to_ema200_pct:.1f}% above EMA200, slope +{ema50_slope:.2f}%, ADX {adx:.0f}",
            features=features,
        )

    if dist_to_ema200_pct > 5:
        # Even without strong slope, far above EMA200 = trending
        confidence = min(1.0, 0.5 + dist_to_ema200_pct * 0.015)
        return RegimeResult(
            regime="TREND",
            confidence=round(confidence, 3),
            reason=f"price +{dist_to_ema200_pct:.1f}% above EMA200 (structurally bullish)",
            features=features,
        )

    # ═══════════════════════════════════════════════════
    # RANGE: price near EMA200, flat, oscillating
    # ═══════════════════════════════════════════════════
    confidence = 0.5
    if abs(dist_to_ema200_pct) < 3:
        confidence += 0.15
    if abs(ema50_slope) < 0.2:
        confidence += 0.1
    if adx < 20:
        confidence += 0.1

    return RegimeResult(
        regime="RANGE",
        confidence=round(min(1.0, confidence), 3),
        reason=f"price {dist_to_ema200_pct:+.1f}% from EMA200, slope {ema50_slope:+.2f}%, ADX {adx:.0f}",
        features=features,
    )
