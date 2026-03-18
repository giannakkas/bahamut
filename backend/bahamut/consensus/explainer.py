"""
Bahamut.AI Decision Explainer

Produces structured reasoning from the data flowing through the pipeline.
Every decision gets a machine-readable + human-readable explanation
answering: WHY this direction, WHY this score, WHY this execution mode.

Output format:
{
    "direction": "LONG",
    "label": "SIGNAL",
    "factors": [
        {"name": "trust", "status": "high", "value": 1.32, "impact": "positive", "detail": "..."},
        {"name": "disagreement", "status": "low", "value": 0.21, "impact": "positive", "detail": "..."},
        ...
    ],
    "blocked_flags": [],
    "narrative": "Decision: LONG. Trust is high (1.32), agents show low disagreement (0.21)...",
    "score_breakdown": {"raw": 0.72, "trust_dampened": 0.72, "confidence_dampened": 0.72, "disagreement_penalized": 0.72, "final": 0.72}
}
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class DecisionFactor:
    name: str
    status: str          # "high", "low", "moderate", "clear", "blocked", "ok", "warning"
    value: float = 0.0
    impact: str = "neutral"  # "positive", "negative", "neutral", "blocking"
    detail: str = ""

    def to_dict(self):
        return {"name": self.name, "status": self.status, "value": round(self.value, 3),
                "impact": self.impact, "detail": self.detail}


@dataclass
class DecisionExplanation:
    direction: str = "NO_TRADE"
    label: str = "NO_TRADE"
    factors: list = field(default_factory=list)
    blocked_flags: list = field(default_factory=list)
    narrative: str = ""
    score_breakdown: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "direction": self.direction, "label": self.label,
            "factors": [f.to_dict() for f in self.factors],
            "blocked_flags": self.blocked_flags,
            "narrative": self.narrative,
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
        }


def explain_decision(
    direction: str,
    label: str,
    final_score: float,
    mean_trust: float,
    disagreement_index: float,
    disagreement_gate: str,
    regime: str,
    risk_flags: list,
    risk_can_trade: bool,
    system_confidence: float = None,
    agreement_pct: float = 0.0,
    trading_profile: str = "BALANCED",
    contributions: list = None,
    blocked: bool = False,
    block_reason: str = None,
) -> DecisionExplanation:
    """Build a structured explanation from all decision inputs."""

    ex = DecisionExplanation(direction=direction, label=label)
    factors = []
    blocked_flags = []

    # ── 1. Trust ──
    if mean_trust >= 1.2:
        factors.append(DecisionFactor("trust", "high", mean_trust, "positive",
                                       f"Agent trust is strong ({mean_trust:.2f}), full weight applied"))
    elif mean_trust >= 0.85:
        factors.append(DecisionFactor("trust", "moderate", mean_trust, "neutral",
                                       f"Trust is adequate ({mean_trust:.2f}), no dampening"))
    elif mean_trust >= 0.5:
        dampening = 0.5 + 0.5 * mean_trust
        factors.append(DecisionFactor("trust", "low", mean_trust, "negative",
                                       f"Low trust ({mean_trust:.2f}) → score dampened ×{dampening:.2f}"))
    else:
        factors.append(DecisionFactor("trust", "critical", mean_trust, "blocking",
                                       f"Trust collapsed ({mean_trust:.2f}) → execution blocked"))
        blocked_flags.append(f"TRUST_FLOOR: {mean_trust:.2f} < 0.50")

    # ── 2. Disagreement ──
    if disagreement_gate == "BLOCKED":
        factors.append(DecisionFactor("disagreement", "blocked", disagreement_index, "blocking",
                                       f"Disagreement index {disagreement_index:.2f} → BLOCKED gate"))
        blocked_flags.append(f"DISAGREEMENT_BLOCKED: {disagreement_index:.3f}")
    elif disagreement_gate == "APPROVAL_ONLY":
        factors.append(DecisionFactor("disagreement", "elevated", disagreement_index, "negative",
                                       f"Disagreement {disagreement_index:.2f} → approval required, size halved"))
    elif disagreement_index > 0.3:
        factors.append(DecisionFactor("disagreement", "moderate", disagreement_index, "neutral",
                                       f"Moderate disagreement ({disagreement_index:.2f}), within tolerance"))
    else:
        factors.append(DecisionFactor("disagreement", "low", disagreement_index, "positive",
                                       f"Low disagreement ({disagreement_index:.2f}), agents aligned"))

    # ── 3. Regime ──
    regime_impact = "positive" if regime in ("RISK_ON", "TREND_CONTINUATION") else \
                    "neutral" if regime in ("LOW_VOL", "RANGE") else "negative"
    regime_detail = {
        "RISK_ON": "Risk-on environment favors directional trades",
        "TREND_CONTINUATION": "Active trend supports momentum signals",
        "LOW_VOL": "Low volatility — technical signals more reliable",
        "HIGH_VOL": "High volatility — wider stops, reduced confidence",
        "RISK_OFF": "Risk-off — defensive positioning preferred",
        "CRISIS": "Crisis regime — most trades blocked or heavily reduced",
    }.get(regime, f"Regime: {regime}")
    factors.append(DecisionFactor("regime", regime.lower().replace("_", " "),
                                   0.0, regime_impact, regime_detail))

    # ── 4. Risk ──
    if not risk_can_trade:
        factors.append(DecisionFactor("risk", "vetoed", 0.0, "blocking",
                                       f"Risk agent veto: {', '.join(risk_flags)}"))
        blocked_flags.append(f"RISK_VETO: {', '.join(risk_flags)}")
    elif risk_flags:
        factors.append(DecisionFactor("risk", "warning", len(risk_flags), "negative",
                                       f"Active risk flags: {', '.join(risk_flags)}"))
    else:
        factors.append(DecisionFactor("risk", "clear", 0.0, "positive",
                                       "No risk flags active"))

    # ── 5. System confidence ──
    if system_confidence is not None:
        if system_confidence >= 0.60:
            factors.append(DecisionFactor("system_confidence", "ok", system_confidence, "positive",
                                           f"System confidence {system_confidence:.2f} — no constraints"))
        elif system_confidence >= 0.40:
            factors.append(DecisionFactor("system_confidence", "moderate", system_confidence, "negative",
                                           f"Reduced confidence ({system_confidence:.2f}) → size reduced"))
        elif system_confidence >= 0.25:
            factors.append(DecisionFactor("system_confidence", "low", system_confidence, "negative",
                                           f"Low confidence ({system_confidence:.2f}) → approval required"))
        else:
            factors.append(DecisionFactor("system_confidence", "critical", system_confidence, "blocking",
                                           f"Confidence collapsed ({system_confidence:.2f}) → blocked"))
            blocked_flags.append(f"LOW_CONFIDENCE: {system_confidence:.3f}")

    # ── 6. Confidence calibration ──
    if contributions is not None:
        overconfident = [c for c in contributions
                         if c.get("confidence", 0) > 0.8 and c.get("effective_contribution", 0) < 0]
        if overconfident:
            names = ", ".join(c["agent_id"].replace("_agent", "") for c in overconfident)
            factors.append(DecisionFactor("calibration", "warning", len(overconfident), "negative",
                                           f"High-confidence dissenters: {names}"))
        else:
            factors.append(DecisionFactor("calibration", "ok", 0.0, "neutral",
                                           "No overconfident dissenters"))

    # ── 7. Agreement ──
    if agreement_pct >= 0.8:
        factors.append(DecisionFactor("agreement", "strong", agreement_pct, "positive",
                                       f"{agreement_pct:.0%} of agents agree on direction"))
    elif agreement_pct >= 0.5:
        factors.append(DecisionFactor("agreement", "moderate", agreement_pct, "neutral",
                                       f"{agreement_pct:.0%} agreement — slim majority"))
    else:
        factors.append(DecisionFactor("agreement", "weak", agreement_pct, "negative",
                                       f"Only {agreement_pct:.0%} agreement — no clear majority"))

    # ── Build narrative ──
    if blocked or blocked_flags:
        narrative = f"Decision: {direction} ({label}). "
        narrative += "BLOCKED — " + "; ".join(blocked_flags) + ". "
    else:
        positive = [f for f in factors if f.impact == "positive"]
        negative = [f for f in factors if f.impact == "negative"]
        narrative = f"Decision: {direction}. "
        if positive:
            narrative += "Because: " + ", ".join(
                f"{f.name} is {f.status}" + (f" ({f.value:.2f})" if f.value else "")
                for f in positive
            ) + ". "
        if negative:
            narrative += "Concerns: " + ", ".join(
                f"{f.name} {f.status}" + (f" ({f.value:.2f})" if f.value else "")
                for f in negative
            ) + ". "

    ex.factors = factors
    ex.blocked_flags = blocked_flags
    ex.narrative = narrative.strip()
    ex.score_breakdown = {"final": final_score}

    return ex
