"""
Bahamut.AI Quality Ratio Engine

Computes: quality_ratio = expected_return / abs(marginal_risk)

Expected return proxy:
  Based on signal strength (consensus score), ATR-based target distance,
  and signal label bonus. Structured for future replacement with a
  more sophisticated model.

Integration:
  - Very low ratio (< min_allow) → reduce or block
  - Acceptable ratio → allow with normal size
  - Strong ratio (> strong) → can justify reallocation
"""
import structlog
from dataclasses import dataclass
from bahamut.admin.config import get_config

logger = structlog.get_logger()


@dataclass
class QualityRatioResult:
    expected_return: float = 0.0    # estimated $ return
    marginal_risk: float = 0.0      # $ risk added to portfolio
    quality_ratio: float = 0.0      # expected_return / abs(marginal_risk)
    signal_strength: float = 0.0    # consensus score used
    target_pct: float = 0.0         # estimated move %
    risk_level: str = "OK"          # OK / REDUCE / APPROVAL / BLOCK

    def to_dict(self):
        return {
            "expected_return": round(self.expected_return, 2),
            "marginal_risk": round(self.marginal_risk, 2),
            "quality_ratio": round(self.quality_ratio, 3),
            "signal_strength": round(self.signal_strength, 3),
            "target_pct": round(self.target_pct, 4),
            "risk_level": self.risk_level,
        }


def compute_quality_ratio(
    consensus_score: float,
    signal_label: str,
    proposed_value: float,
    atr: float,
    entry_price: float,
    marginal_risk_result=None,
) -> QualityRatioResult:
    """
    Compute quality ratio for a proposed trade.

    Expected return proxy:
      target_pct = ATR-based expected move × signal confidence
      expected_return = proposed_value × target_pct

    Marginal risk:
      From MarginalRiskResult.worst_case_marginal (absolute $ value)
      If not available, falls back to proposed_value × 2% (conservative estimate)
    """
    result = QualityRatioResult()
    result.signal_strength = consensus_score

    # ── Expected return proxy ──
    # Base target: 1.5× ATR (between SL at 2×ATR and TP at 3×ATR)
    if entry_price > 0 and atr > 0:
        base_target_pct = (atr * 1.5) / entry_price
    else:
        base_target_pct = 0.01  # 1% fallback

    # Scale by signal quality
    signal_mult = consensus_score  # 0-1
    label_bonus = {"STRONG_SIGNAL": 1.2, "SIGNAL": 1.0, "WEAK_SIGNAL": 0.6}.get(signal_label, 0.8)
    result.target_pct = base_target_pct * signal_mult * label_bonus
    result.expected_return = proposed_value * result.target_pct

    # ── Marginal risk ──
    if marginal_risk_result and hasattr(marginal_risk_result, 'worst_case_marginal'):
        result.marginal_risk = abs(marginal_risk_result.worst_case_marginal)
    else:
        # Conservative fallback: 2% of position value
        result.marginal_risk = proposed_value * 0.02

    # Avoid division by zero
    if result.marginal_risk > 0:
        result.quality_ratio = result.expected_return / result.marginal_risk
    else:
        result.quality_ratio = 10.0  # no risk = great ratio

    # Bound ratio for safety
    result.quality_ratio = max(0.0, min(10.0, result.quality_ratio))

    # Risk level from central config
    min_allow = get_config("quality_ratio.min_allow", 0.5)
    reduce_below = get_config("quality_ratio.reduce_below", 1.0)

    if result.quality_ratio < min_allow * 0.5:
        result.risk_level = "BLOCK"
    elif result.quality_ratio < min_allow:
        result.risk_level = "APPROVAL"
    elif result.quality_ratio < reduce_below:
        result.risk_level = "REDUCE"
    else:
        result.risk_level = "OK"

    logger.info("quality_ratio_computed",
                 ratio=round(result.quality_ratio, 3),
                 expected=round(result.expected_return, 2),
                 marginal=round(result.marginal_risk, 2),
                 level=result.risk_level)

    return result
