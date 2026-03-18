"""
Bahamut.AI Disagreement Engine

Computes a composite disagreement_index from 5 components:
  1. directional_dispersion — variance of agent directional scores
  2. contradiction_score — high-confidence opposing pairs
  3. confidence_variance — spread of confidence levels
  4. challenge_severity — impact of challenge round
  5. risk_rejection_penalty — risk agent flags/veto

Gates execution: CLEAR / APPROVAL_ONLY / BLOCKED (profile-aware)
"""
import math
from collections import Counter
import structlog
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeResponseSchema, DisagreementMetrics,
)

logger = structlog.get_logger()

COMPONENT_WEIGHTS = {
    "directional_dispersion": 0.30,
    "contradiction_score": 0.25,
    "confidence_variance": 0.15,
    "challenge_severity": 0.15,
    "risk_rejection": 0.15,
}

GATE_THRESHOLDS = {
    "CONSERVATIVE": {"low": 0.30, "high": 0.50},
    "BALANCED": {"low": 0.40, "high": 0.60},
    "AGGRESSIVE": {"low": 0.55, "high": 0.75},
}


class DisagreementEngine:

    def calculate(
        self,
        directional_outputs: list[AgentOutputSchema],
        risk_output: AgentOutputSchema | None,
        challenges: list[ChallengeResponseSchema],
        trading_profile: str = "BALANCED",
    ) -> DisagreementMetrics:
        if not directional_outputs:
            return DisagreementMetrics(
                execution_gate="BLOCKED",
                gate_reasons=["No agent outputs available"],
            )

        # 1. Directional dispersion
        dir_scores = []
        for o in directional_outputs:
            if o.directional_bias == "LONG":
                dir_scores.append(float(o.confidence))
            elif o.directional_bias == "SHORT":
                dir_scores.append(-float(o.confidence))
            elif o.directional_bias == "NEUTRAL":
                dir_scores.append(0.0)

        if len(dir_scores) >= 2:
            mean = sum(dir_scores) / len(dir_scores)
            variance = sum((s - mean) ** 2 for s in dir_scores) / len(dir_scores)
            directional_dispersion = min(1.0, math.sqrt(variance))
        else:
            directional_dispersion = 0.0

        # 2. Contradiction count & score
        contradiction_count = 0
        contradiction_intensity = 0.0
        longs = [o for o in directional_outputs if o.directional_bias == "LONG"]
        shorts = [o for o in directional_outputs if o.directional_bias == "SHORT"]
        for la in longs:
            for sa in shorts:
                if float(la.confidence) > 0.5 and float(sa.confidence) > 0.5:
                    contradiction_count += 1
                    contradiction_intensity += float(la.confidence) * float(sa.confidence)
        max_pairs = max(1, len(longs) * len(shorts))
        normalized_contradiction = min(1.0, contradiction_intensity / max(1.0, max_pairs * 0.5))

        # 3. Confidence variance
        confidences = [float(o.confidence) for o in directional_outputs]
        if len(confidences) >= 2:
            c_mean = sum(confidences) / len(confidences)
            c_var = sum((c - c_mean) ** 2 for c in confidences) / len(confidences)
            confidence_variance = min(1.0, math.sqrt(c_var) * 2)
        else:
            confidence_variance = 0.0

        # 4. Challenge severity
        challenge_severity = 0.0
        if challenges:
            for ch in challenges:
                if ch.response == "VETO": challenge_severity += 0.4
                elif ch.response == "PARTIAL": challenge_severity += 0.2
                elif ch.response == "ACCEPT": challenge_severity += 0.1
                elif ch.response == "REJECT": challenge_severity += 0.15
            challenge_severity = min(1.0, challenge_severity / max(1, len(challenges)) * 2)

        # 5. Risk rejection penalty
        risk_rejection_penalty = 0.0
        if risk_output:
            risk_flags = risk_output.meta.get("risk_flags", [])
            can_trade = risk_output.meta.get("can_trade", True)
            if not can_trade:
                risk_rejection_penalty = 1.0
            elif risk_flags:
                risk_rejection_penalty = min(0.8, len(risk_flags) * 0.2)

        # Composite index
        w = COMPONENT_WEIGHTS
        disagreement_index = (
            w["directional_dispersion"] * directional_dispersion
            + w["contradiction_score"] * normalized_contradiction
            + w["confidence_variance"] * confidence_variance
            + w["challenge_severity"] * challenge_severity
            + w["risk_rejection"] * risk_rejection_penalty
        )
        disagreement_index = round(min(1.0, max(0.0, disagreement_index)), 4)

        # Execution gate
        thresholds = GATE_THRESHOLDS.get(trading_profile, GATE_THRESHOLDS["BALANCED"])
        gate_reasons = []

        if risk_rejection_penalty >= 1.0:
            execution_gate = "BLOCKED"
            gate_reasons.append("Risk agent vetoed trade")
        elif disagreement_index >= thresholds["high"]:
            execution_gate = "BLOCKED"
            gate_reasons.append(f"Disagreement {disagreement_index:.3f} >= {thresholds['high']:.2f}")
        elif disagreement_index >= thresholds["low"]:
            execution_gate = "APPROVAL_ONLY"
            gate_reasons.append(f"Disagreement {disagreement_index:.3f} >= {thresholds['low']:.2f}")
        else:
            execution_gate = "CLEAR"

        if contradiction_count >= 3 and execution_gate == "CLEAR":
            execution_gate = "APPROVAL_ONLY"
            gate_reasons.append(f"{contradiction_count} contradictions")

        logger.info("disagreement_computed", index=disagreement_index,
                     contradictions=contradiction_count, gate=execution_gate)

        return DisagreementMetrics(
            disagreement_index=disagreement_index,
            contradiction_count=contradiction_count,
            challenge_severity=round(challenge_severity, 4),
            directional_dispersion=round(directional_dispersion, 4),
            confidence_variance=round(confidence_variance, 4),
            risk_rejection_penalty=round(risk_rejection_penalty, 4),
            execution_gate=execution_gate,
            gate_reasons=gate_reasons,
        )


disagreement_engine = DisagreementEngine()
