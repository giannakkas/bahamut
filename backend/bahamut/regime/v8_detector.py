"""
Bahamut v8 — Regime Detector

Classifies market into one of 3 regimes:
  TREND — price above EMA200, positive slope, trending behavior
  RANGE — price near EMA200, flat EMAs, oscillating
  CRASH — price below EMA200, elevated volatility, breakdown

Rules are deterministic, explainable, no future leakage.

Phase 1 Item 3 changes:
  - EMA50 slope computed from the true EMA series (not mean-of-closes proxy).
  - RegimeResult now separates structural_regime, sentiment_overlay,
    effective_regime, and regime_confidence. The detector only ever sets
    the structural answer; overlays are applied externally by the caller
    and recorded in the same result object so downstream can inspect both.
"""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class RegimeResult:
    # ── Structural answer (from price/indicators only — no sentiment, no overrides) ──
    regime: str = "RANGE"              # kept for backward compat; == structural_regime
    structural_regime: str = "RANGE"   # TREND / RANGE / CRASH — the honest answer
    regime_confidence: float = 0.5     # 0–1 confidence in the structural answer

    # ── Overlays applied by the caller (orchestrator). Detector never sets these. ──
    sentiment_overlay: str = ""        # "" | "long_block" | "short_block" etc.
    override_applied: str = ""         # "" | "structural_crash_override" | ...
    effective_regime: str = ""         # final regime strategies should use; set by caller

    # ── Diagnostics / provenance ──
    confidence: float = 0.5            # backward-compat alias for regime_confidence
    reason: str = ""
    features: dict = field(default_factory=dict)

    def __post_init__(self):
        # Keep legacy aliases consistent when only one side was set
        if self.structural_regime == "RANGE" and self.regime != "RANGE":
            self.structural_regime = self.regime
        elif self.regime == "RANGE" and self.structural_regime != "RANGE":
            self.regime = self.structural_regime
        if self.regime_confidence == 0.5 and self.confidence != 0.5:
            self.regime_confidence = self.confidence
        elif self.confidence == 0.5 and self.regime_confidence != 0.5:
            self.confidence = self.regime_confidence
        if not self.effective_regime:
            self.effective_regime = self.structural_regime


def _ema_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Exact EMA series — same math as features.indicators._ema_series.
    Kept local to avoid an import cycle (regime/ imports from data/indicators paths already)."""
    result = np.zeros_like(closes, dtype=float)
    mult = 2.0 / (period + 1)
    result[0] = float(closes[0])
    for i in range(1, len(closes)):
        result[i] = (float(closes[i]) - result[i - 1]) * mult + result[i - 1]
    return result


def _compute_ema50_slope(candles: list, current_ema_50: float) -> float:
    """Compute EMA50 slope as percent change over ~10 bars, using the TRUE
    EMA series rather than a mean-of-closes proxy.

    Returns slope in percent. Positive = trending up, negative = trending down.
    Returns 0 if insufficient data.
    """
    if not candles or len(candles) < 60:
        return 0.0
    try:
        closes = np.array([c.get("close", 0) for c in candles], dtype=float)
        if len(closes) < 60 or closes[-1] <= 0:
            return 0.0
        # Build full EMA50 series over available closes, then take slope
        # between current and 10 bars ago.
        ema_series = _ema_series(closes, 50)
        prior = float(ema_series[-11])
        curr = float(ema_series[-1]) if current_ema_50 <= 0 else float(current_ema_50)
        if prior <= 0:
            return 0.0
        return round((curr - prior) / prior * 100, 4)
    except Exception:
        return 0.0


def detect_regime(indicators: dict, candles: list = None) -> RegimeResult:
    """
    Detect structural market regime from price/indicators only.

    The detector NEVER applies sentiment or overrides. Callers that want to
    overlay sentiment or force a regime should do so on the returned
    RegimeResult by setting sentiment_overlay / override_applied /
    effective_regime — keeping the structural answer intact for audit.

    indicators: from compute_indicators() — needs close, ema_20, ema_50, ema_200, atr_14, adx_14
    candles: optional recent candles (>= 60 ideally) for true EMA slope
    """
    close = indicators.get("close", 0)
    ema_50 = indicators.get("ema_50", 0)
    ema_200 = indicators.get("ema_200", 0)
    atr = indicators.get("atr_14", 0)
    adx = indicators.get("adx_14", 20)

    if close <= 0 or ema_200 <= 0:
        return RegimeResult(
            regime="RANGE", structural_regime="RANGE",
            regime_confidence=0.3, confidence=0.3,
            reason="insufficient data",
        )

    # ── Core features ──
    dist_to_ema200_pct = (close - ema_200) / ema_200 * 100
    atr_pct = (atr / close * 100) if close > 0 else 0

    # EMA50 slope: TRUE EMA series slope (not mean-of-closes proxy)
    ema50_slope = _compute_ema50_slope(candles, ema_50)

    features = {
        "price_vs_ema200": round(dist_to_ema200_pct, 2),
        "ema50_slope": round(ema50_slope, 3),
        "ema50_slope_method": "true_ema_series" if (candles and len(candles) >= 60) else "insufficient_history",
        "atr_pct": round(atr_pct, 3),
        "distance_to_ema200_pct": round(abs(dist_to_ema200_pct), 2),
        "adx": round(adx, 1),
    }

    def _result(reg: str, conf: float, reason: str) -> RegimeResult:
        c = round(min(1.0, conf), 3)
        return RegimeResult(
            regime=reg, structural_regime=reg,
            regime_confidence=c, confidence=c,
            effective_regime=reg,
            reason=reason, features=features,
        )

    # ═══════════════════════════════════════════════════
    # CRASH: price well below EMA200 + elevated vol
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct < -5 and atr_pct > 2.5:
        conf = 0.6 + abs(dist_to_ema200_pct) * 0.02 + atr_pct * 0.05
        return _result("CRASH", conf,
            f"price {dist_to_ema200_pct:+.1f}% below EMA200, ATR {atr_pct:.1f}% (elevated)")

    if dist_to_ema200_pct < -8:
        conf = 0.5 + abs(dist_to_ema200_pct) * 0.03
        return _result("CRASH", conf,
            f"price {dist_to_ema200_pct:+.1f}% below EMA200 (deep breakdown)")

    # ═══════════════════════════════════════════════════
    # CRASH (soft): below EMA200 + negative slope = slow bleed
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct < -2 and ema50_slope < -0.15:
        conf = 0.5 + abs(dist_to_ema200_pct) * 0.03 + abs(ema50_slope) * 0.1
        return _result("CRASH", conf,
            f"price {dist_to_ema200_pct:+.1f}% below EMA200, slope {ema50_slope:+.2f}% (slow bleed)")

    # ═══════════════════════════════════════════════════
    # TREND: price above EMA200, positive slope, trending
    # ═══════════════════════════════════════════════════
    if dist_to_ema200_pct > 3 and ema50_slope > 0.1:
        conf = 0.5 + dist_to_ema200_pct * 0.02 + ema50_slope * 0.1
        if adx > 25:
            conf += 0.1
        return _result("TREND", conf,
            f"price +{dist_to_ema200_pct:.1f}% above EMA200, slope +{ema50_slope:.2f}%, ADX {adx:.0f}")

    if dist_to_ema200_pct > 5:
        conf = 0.5 + dist_to_ema200_pct * 0.015
        return _result("TREND", conf,
            f"price +{dist_to_ema200_pct:.1f}% above EMA200 (structurally bullish)")

    # ═══════════════════════════════════════════════════
    # RANGE: price near EMA200, flat, oscillating
    # ═══════════════════════════════════════════════════
    conf = 0.5
    if abs(dist_to_ema200_pct) < 3:
        conf += 0.15
    if abs(ema50_slope) < 0.2:
        conf += 0.1
    if adx < 20:
        conf += 0.1

    return _result("RANGE", conf,
        f"price {dist_to_ema200_pct:+.1f}% from EMA200, slope {ema50_slope:+.2f}%, ADX {adx:.0f}")
