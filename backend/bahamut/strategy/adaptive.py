"""
Bahamut v3 — Adaptive Strategy Layer

Dynamic SL/TP/position sizing based on:
  - Volatility regime
  - Market structure regime
  - Cross-asset risk score
  - Signal confidence

Replaces static parameters with regime-aware functions.
"""
from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger()


@dataclass
class AdaptiveParams:
    """Dynamic trading parameters for a single trade."""
    sl_multiplier: float = 2.0      # ATR multiplier for stop loss
    tp_multiplier: float = 3.0      # ATR multiplier for take profit
    size_multiplier: float = 1.0    # Position size multiplier (0.2 - 1.2)
    max_hold_candles: int = 12      # Max holding period
    urgency: str = "NEXT_BAR"       # IMMEDIATE or NEXT_BAR
    regime_label: str = ""
    reasoning: list = None

    def __post_init__(self):
        if self.reasoning is None:
            self.reasoning = []

    def to_dict(self) -> dict:
        return {
            "sl_multiplier": round(self.sl_multiplier, 2),
            "tp_multiplier": round(self.tp_multiplier, 2),
            "size_multiplier": round(self.size_multiplier, 2),
            "max_hold_candles": self.max_hold_candles,
            "urgency": self.urgency,
            "regime_label": self.regime_label,
            "reasoning": self.reasoning,
        }


class AdaptiveStrategy:
    """
    Computes dynamic trade parameters based on regime and context.
    """

    def compute(
        self,
        regime: Optional[dict] = None,
        cross_asset: Optional[dict] = None,
        signal_confidence: float = 0.5,
        asset_class: str = "fx",
        direction: str = "",
    ) -> AdaptiveParams:
        """
        Compute adaptive parameters.

        regime: CompositeRegime.to_dict() or None
        cross_asset: CrossAssetContext.to_dict() or None
        signal_confidence: 0-1 from consensus
        asset_class: fx, crypto, commodities, stocks, etc.
        direction: LONG or SHORT
        """
        params = AdaptiveParams()
        reasons = []

        # ── Base parameters from asset class ──
        base = ASSET_CLASS_BASES.get(asset_class, ASSET_CLASS_BASES["fx"])
        params.sl_multiplier = base["sl"]
        params.tp_multiplier = base["tp"]
        params.max_hold_candles = base["hold"]

        # ── Volatility Regime Adjustments ──
        if regime:
            vol_state = regime.get("volatility", {}).get("state", "NORMAL")
            struct_state = regime.get("structure", {}).get("state", "RANGE")
            primary = regime.get("primary_label", "NORMAL")
            regime_risk_mult = regime.get("risk_multiplier", 1.0)

            params.regime_label = primary

            # Volatility → SL/TP width
            if vol_state == "EXTREME":
                params.sl_multiplier *= 1.5
                params.tp_multiplier *= 1.3
                params.size_multiplier *= 0.3
                params.max_hold_candles = max(6, params.max_hold_candles // 2)
                reasons.append(f"EXTREME vol: SL×1.5, TP×1.3, size×0.3")

            elif vol_state == "HIGH_VOL":
                params.sl_multiplier *= 1.3
                params.tp_multiplier *= 1.2
                params.size_multiplier *= 0.6
                reasons.append(f"HIGH_VOL: SL×1.3, size×0.6")

            elif vol_state == "LOW_VOL":
                params.sl_multiplier *= 0.75
                params.tp_multiplier *= 0.85
                params.size_multiplier *= 1.0
                reasons.append(f"LOW_VOL: tighter SL×0.75")

            # Structure → TP and hold
            if struct_state in ("TRENDING_UP", "TRENDING_DOWN"):
                params.tp_multiplier *= 1.2  # Let winners run in trends
                params.max_hold_candles = int(params.max_hold_candles * 1.3)
                reasons.append(f"TRENDING: TP×1.2, longer hold")

            elif struct_state == "RANGE":
                params.tp_multiplier *= 0.8   # Take profits quicker in range
                params.sl_multiplier *= 0.9   # Tighter SL in range
                reasons.append(f"RANGE: TP×0.8, tighter SL")

            elif struct_state == "CHOPPY":
                params.size_multiplier *= 0.7
                params.tp_multiplier *= 0.75
                reasons.append(f"CHOPPY: size×0.7, reduced TP")

            # Apply regime risk multiplier
            params.size_multiplier *= regime_risk_mult

        # ── Cross-Asset Adjustments ──
        if cross_asset:
            risk_score = cross_asset.get("risk_regime", {}).get("score", 0)
            risk_label = cross_asset.get("risk_regime", {}).get("label", "NEUTRAL")
            ca_adjustment = cross_asset.get("signal_adjustment", 1.0)
            bias = cross_asset.get("bias_adjustment", "NONE")

            # Apply cross-asset signal adjustment to size
            params.size_multiplier *= ca_adjustment

            if risk_label == "RISK_OFF" and direction == "LONG":
                params.size_multiplier *= 0.7
                reasons.append(f"RISK_OFF: long size reduced")
            elif risk_label == "RISK_ON" and direction == "SHORT":
                params.size_multiplier *= 0.7
                reasons.append(f"RISK_ON: short size reduced")

            if bias == "BLOCK":
                params.size_multiplier = 0.0
                reasons.append("Cross-asset BLOCK")

        # ── Signal Confidence Scaling ──
        if signal_confidence < 0.5:
            params.size_multiplier *= 0.7
            reasons.append(f"Low confidence ({signal_confidence:.2f}): size×0.7")
        elif signal_confidence > 0.80:
            params.size_multiplier *= 1.1
            reasons.append(f"High confidence ({signal_confidence:.2f}): size×1.1")

        # ── Clamp final values ──
        params.sl_multiplier = round(max(0.5, min(4.0, params.sl_multiplier)), 2)
        params.tp_multiplier = round(max(0.5, min(6.0, params.tp_multiplier)), 2)
        params.size_multiplier = round(max(0.15, min(1.2, params.size_multiplier)), 2)
        params.max_hold_candles = max(3, min(48, params.max_hold_candles))
        params.reasoning = reasons

        return params


# Asset class base parameters
ASSET_CLASS_BASES = {
    "fx": {"sl": 1.5, "tp": 2.25, "hold": 12},
    "crypto": {"sl": 2.0, "tp": 3.0, "hold": 18},
    "commodities": {"sl": 1.8, "tp": 2.7, "hold": 15},
    "stocks": {"sl": 2.0, "tp": 3.0, "hold": 20},
    "indices": {"sl": 1.5, "tp": 2.5, "hold": 12},
    "bonds": {"sl": 1.5, "tp": 2.0, "hold": 24},
}


# Singleton
adaptive_strategy = AdaptiveStrategy()
