"""
Bahamut.AI Consensus Engine
The core decision-making algorithm. Implements the weighted multi-agent consensus
from Phase 1 Section 3.
"""
from collections import Counter
from uuid import uuid4
from typing import Optional
import structlog

from bahamut.agents.schemas import (
    AgentOutputSchema, ConsensusDecisionSchema, TradePlanSchema,
    DisagreementMetrics,
)

logger = structlog.get_logger()

# ── Base weights by asset class ──
# Only includes agents that actually exist: technical, macro, volatility, sentiment, liquidity
# risk_agent is handled separately (veto power, not scored)
BASE_WEIGHTS = {
    "fx": {
        "macro_agent": 0.25, "volatility_agent": 0.15,
        "liquidity_agent": 0.15, "sentiment_agent": 0.15,
        "technical_agent": 0.30,
    },
    "indices": {
        "macro_agent": 0.20, "volatility_agent": 0.20,
        "liquidity_agent": 0.15, "sentiment_agent": 0.15,
        "technical_agent": 0.30,
    },
    "commodities": {
        "macro_agent": 0.20, "volatility_agent": 0.15,
        "liquidity_agent": 0.15, "sentiment_agent": 0.25,
        "technical_agent": 0.25,
    },
    "crypto": {
        "macro_agent": 0.10, "volatility_agent": 0.15,
        "liquidity_agent": 0.20, "sentiment_agent": 0.25,
        "technical_agent": 0.30,
    },
    "bonds": {
        "macro_agent": 0.30, "volatility_agent": 0.15,
        "liquidity_agent": 0.10, "sentiment_agent": 0.15,
        "technical_agent": 0.30,
    },
}

# ── Regime relevance multipliers ──
REGIME_RELEVANCE = {
    "RISK_OFF": {
        "macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 0.9,
        "technical_agent": 0.5, "liquidity_agent": 0.7,
    },
    "RISK_ON": {
        "macro_agent": 0.8, "technical_agent": 1.0,
        "volatility_agent": 0.6, "sentiment_agent": 0.7,
        "liquidity_agent": 0.8,
    },
    "HIGH_VOL": {
        "volatility_agent": 1.0, "macro_agent": 0.7,
        "technical_agent": 0.5, "sentiment_agent": 0.8,
        "liquidity_agent": 0.8,
    },
    "LOW_VOL": {
        "technical_agent": 1.0, "liquidity_agent": 1.0,
        "macro_agent": 0.6, "volatility_agent": 0.5,
        "sentiment_agent": 0.5,
    },
    "CRISIS": {
        "macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 1.0,
        "technical_agent": 0.3, "liquidity_agent": 0.6,
    },
    "TREND_CONTINUATION": {
        "technical_agent": 1.0, "macro_agent": 0.8,
        "volatility_agent": 0.6, "sentiment_agent": 0.6,
        "liquidity_agent": 0.7,
    },
}

OPPOSITION_FACTOR = 0.6

# ── Profile threshold defaults (will be loaded from DB in production) ──
PROFILE_THRESHOLDS = {
    "CONSERVATIVE": {
        "strong_signal": 0.82, "signal": 0.70, "weak_signal": 0.55,
        "min_agreement": 7, "min_confidence": 0.60,
    },
    "BALANCED": {
        "strong_signal": 0.72, "signal": 0.58, "weak_signal": 0.45,
        "min_agreement": 6, "min_confidence": 0.50,
    },
    "AGGRESSIVE": {
        "strong_signal": 0.62, "signal": 0.48, "weak_signal": 0.35,
        "min_agreement": 5, "min_confidence": 0.40,
    },
}


class ConsensusEngine:
    """Implements the weighted multi-agent consensus algorithm."""

    def calculate(
        self,
        agent_outputs: list[AgentOutputSchema],
        asset_class: str,
        regime: str,
        trading_profile: str,
        trust_scores: dict[str, float] = None,
        weight_overrides: dict[str, float] = None,
        resolved_weights: dict[str, float] = None,
        disagreement_metrics: DisagreementMetrics = None,
        system_confidence: float = None,
    ) -> ConsensusDecisionSchema:
        """
        Full consensus calculation. Returns a ConsensusDecisionSchema.

        Steps:
        1. Determine candidate direction
        2. Load weights, trust, regime relevance
        3. Calculate raw weighted score
        4. Apply agreement penalty
        5. Apply confidence floor
        6. Map to decision
        7. Build output struct
        """
        trust_scores = trust_scores or {}
        weight_overrides = weight_overrides or {}

        # ── RISK VETO — hard override, checked FIRST ──
        risk_output = next((o for o in agent_outputs if o.agent_id == "risk_agent"), None)
        risk_flags = []
        if risk_output:
            risk_flags = risk_output.meta.get("risk_flags", [])
            if not risk_output.meta.get("can_trade", True):
                cycle_id = agent_outputs[0].cycle_id if agent_outputs else uuid4()
                return ConsensusDecisionSchema(
                    consensus_id=uuid4(), cycle_id=cycle_id,
                    asset=agent_outputs[0].asset if agent_outputs else "",
                    direction="NO_TRADE", final_score=0.0,
                    decision="BLOCKED", agreement_pct=0.0,
                    agent_contributions=[], disagreement=disagreement_metrics,
                    regime=regime, regime_confidence=0.5,
                    risk_flags=risk_flags, blocked=True,
                    block_reason=f"Risk Agent veto: {', '.join(risk_flags)}",
                    explanation=f"Decision: NO_TRADE. BLOCKED — Risk Agent veto: {', '.join(risk_flags)}.",
                    execution_mode="WATCH", trading_profile=trading_profile,
                )

        # Filter out timed-out agents and risk_agent (risk has veto, not scoring weight)
        directional_outputs = [
            o for o in agent_outputs
            if o.agent_id != "risk_agent" and not o.meta.get("timed_out", False)
        ]

        if not directional_outputs:
            return self._no_trade_decision(agent_outputs, regime, trading_profile)

        # ── Step 1: Candidate direction ──
        candidate_dir = self._determine_direction(directional_outputs)
        if candidate_dir == "NO_TRADE":
            return self._no_trade_decision(agent_outputs, regime, trading_profile)

        # ── Step 2: Load parameters ──
        use_resolved = resolved_weights is not None
        if not use_resolved:
            base_weights = BASE_WEIGHTS.get(asset_class, BASE_WEIGHTS["fx"])
            regime_rel = REGIME_RELEVANCE.get(regime, {k: 0.7 for k in base_weights})

        # ── Step 3: Calculate weighted score ──
        aligned_sum = 0.0
        opposed_penalty = 0.0
        total_weight = 0.0
        contributions = []

        for output in directional_outputs:
            aid = output.agent_id
            C = float(output.confidence)

            if use_resolved:
                effective_weight = resolved_weights.get(aid, 0.1)
                T = trust_scores.get(aid, 1.0)
                W = effective_weight
                R = 1.0
            else:
                W = base_weights.get(aid, 0.1) * weight_overrides.get(aid, 1.0)
                T = trust_scores.get(aid, 1.0)
                R = regime_rel.get(aid, 0.7)
                effective_weight = W * T * R

            if output.directional_bias == candidate_dir:
                contrib = effective_weight * C
                aligned_sum += contrib
                total_weight += effective_weight
            elif output.directional_bias == "NEUTRAL":
                total_weight += effective_weight * 0.3
                contrib = 0.0
            else:
                # Opposing
                penalty = effective_weight * C * OPPOSITION_FACTOR
                opposed_penalty += penalty
                total_weight += effective_weight
                contrib = -penalty

            contributions.append({
                "agent_id": aid,
                "bias": output.directional_bias,
                "confidence": C,
                "trust_score": T,
                "base_weight": round(W, 4),
                "regime_relevance": R,
                "effective_weight": round(effective_weight, 4),
                "effective_contribution": round(contrib, 4),
            })

        if total_weight == 0:
            return self._no_trade_decision(agent_outputs, regime, trading_profile)

        raw_score = max(0.0, min(1.0, (aligned_sum - opposed_penalty) / total_weight))

        # ── Step 3b: Aggregate trust dampening ──
        # When ALL agents have low trust, the normalization above cancels it out
        # (0.3*X / 0.3*Y = X/Y). We need a separate penalty for low system confidence.
        agent_trusts = [trust_scores.get(o.agent_id, 1.0) for o in directional_outputs]
        mean_trust = sum(agent_trusts) / len(agent_trusts) if agent_trusts else 1.0
        if mean_trust < 1.0:
            # Maps: trust 0.1 → factor 0.55, trust 0.5 → 0.75, trust 1.0 → 1.0
            trust_dampening = 0.5 + 0.5 * mean_trust
            raw_score *= trust_dampening

        # ── Step 3c: System confidence dampening ──
        # System confidence captures trust stability + disagreement trend +
        # recent performance + calibration health. Low confidence = less aggressive signals.
        if system_confidence is not None and system_confidence < 0.5:
            # Maps: 0.0→0.60, 0.25→0.75, 0.50→1.0 (no dampening above 0.5)
            conf_dampening = 0.6 + 0.8 * system_confidence
            raw_score *= conf_dampening

        # ── Step 4: Agreement penalty ──
        # Agreement: only count agents with a directional opinion (not NEUTRAL)
        dir_counts = Counter(
            o.directional_bias for o in directional_outputs
            if o.directional_bias not in ("NO_TRADE", "NEUTRAL")
        )
        total_directional = sum(dir_counts.values())
        total_agents = len(directional_outputs)
        aligned_count = dir_counts.get(candidate_dir, 0)
        
        # Agreement = aligned / total participating agents (including neutral)
        agreement_pct = aligned_count / total_agents if total_agents > 0 else 0

        thresholds = PROFILE_THRESHOLDS.get(trading_profile, PROFILE_THRESHOLDS["BALANCED"])
        
        # Softer penalty: only penalize if fewer than half of DIRECTIONAL agents agree
        min_agree_ratio = thresholds["min_agreement"] / 9.0
        if total_directional > 0:
            directional_agreement = aligned_count / total_directional
            if directional_agreement < 0.5:
                # Opposing majority - penalize
                raw_score = max(0.0, raw_score * 0.5)
        
        # Still apply threshold check but less aggressively
        if agreement_pct < min_agree_ratio * 0.5:
            raw_score = max(0.0, raw_score * 0.7)

        # ── Step 5: Confidence floor filter ──
        min_conf = thresholds["min_confidence"]
        for output in directional_outputs:
            if (output.confidence < min_conf and
                    output.directional_bias == candidate_dir):
                # Halve contribution of low-confidence aligned agents
                for c in contributions:
                    if c["agent_id"] == output.agent_id:
                        c["effective_contribution"] *= 0.5

        # Recompute after floor (approximate)
        final_score = round(raw_score, 4)

        # ── Step 6: Map to decision ──
        decision = self._map_to_decision(final_score, trading_profile, thresholds)

        # Determine execution mode
        if decision == "STRONG_SIGNAL":
            exec_mode = "AUTO"
        elif decision == "SIGNAL":
            # During paper trading, auto-execute signals to accelerate learning
            from bahamut.warmup import is_warmup_mode
            exec_mode = "AUTO" if is_warmup_mode() else "APPROVAL"
        else:
            exec_mode = "WATCH"

        # Apply disagreement gate (can only downgrade, never upgrade)
        if disagreement_metrics is not None:
            dg = disagreement_metrics.execution_gate
            if dg == "BLOCKED":
                exec_mode = "WATCH"
                if decision not in ("NO_TRADE", "WEAK_SIGNAL"):
                    decision = "WEAK_SIGNAL"
            elif dg == "APPROVAL_ONLY" and exec_mode == "AUTO":
                exec_mode = "APPROVAL"
            # Score penalty for high disagreement
            if disagreement_metrics.disagreement_index > 0.5:
                penalty = (disagreement_metrics.disagreement_index - 0.5) * 0.3
                final_score = round(max(0.0, final_score - penalty), 4)

        # Dissenters
        dissenting = [
            {"agent_id": o.agent_id, "bias": o.directional_bias,
             "confidence": float(o.confidence), "evidence": o.evidence[0].claim if o.evidence else ""}
            for o in directional_outputs
            if o.directional_bias not in (candidate_dir, "NEUTRAL", "NO_TRADE")
        ]

        # risk_flags already captured at top of function (risk veto returns early)
        cycle_id = directional_outputs[0].cycle_id if directional_outputs else uuid4()

        # Build structured explanation
        explanation_text = ""
        try:
            from bahamut.consensus.explainer import explain_decision
            expl = explain_decision(
                direction=candidate_dir, label=decision, final_score=final_score,
                mean_trust=mean_trust, disagreement_index=disagreement_metrics.disagreement_index if disagreement_metrics else 0,
                disagreement_gate=disagreement_metrics.execution_gate if disagreement_metrics else "CLEAR",
                regime=regime, risk_flags=risk_flags, risk_can_trade=True,
                system_confidence=system_confidence, agreement_pct=agreement_pct,
                trading_profile=trading_profile, contributions=contributions,
            )
            explanation_text = expl.narrative
        except Exception as e:
            logger.warning("consensus_explanation_failed", error=str(e))

        return ConsensusDecisionSchema(
            consensus_id=uuid4(),
            cycle_id=cycle_id,
            asset=directional_outputs[0].asset if directional_outputs else "",
            direction=candidate_dir,
            final_score=final_score,
            decision=decision,
            agreement_pct=round(agreement_pct, 3),
            agent_contributions=contributions,
            dissenting_agents=dissenting,
            disagreement=disagreement_metrics,
            regime=regime,
            regime_confidence=0.8,
            risk_flags=risk_flags,
            blocked=False,
            block_reason=None,
            explanation=explanation_text,
            execution_mode=exec_mode,
            trading_profile=trading_profile,
        )

    def _determine_direction(self, outputs: list[AgentOutputSchema]) -> str:
        counts = Counter(
            o.directional_bias for o in outputs
            if o.directional_bias not in ("NO_TRADE", "NEUTRAL")
        )
        if not counts:
            # No directional opinions at all — check if any NEUTRAL agents lean via confidence
            # Still return NO_TRADE if truly no signal
            return "NO_TRADE"
        top_two = counts.most_common(2)
        if len(top_two) > 1 and top_two[0][1] == top_two[1][1]:
            # Tie — break by average confidence
            dir_a, dir_b = top_two[0][0], top_two[1][0]
            conf_a = sum(o.confidence for o in outputs if o.directional_bias == dir_a) / top_two[0][1]
            conf_b = sum(o.confidence for o in outputs if o.directional_bias == dir_b) / top_two[1][1]
            return dir_a if conf_a >= conf_b else dir_b
        return top_two[0][0]

    def _map_to_decision(self, score: float, profile: str, thresholds: dict) -> str:
        if score >= thresholds["strong_signal"]:
            return "STRONG_SIGNAL"
        elif score >= thresholds["signal"]:
            return "SIGNAL"
        elif score >= thresholds["weak_signal"]:
            return "WEAK_SIGNAL"
        return "NO_TRADE"

    def _no_trade_decision(self, outputs, regime, profile) -> ConsensusDecisionSchema:
        cycle_id = outputs[0].cycle_id if outputs else uuid4()
        return ConsensusDecisionSchema(
            consensus_id=uuid4(),
            cycle_id=cycle_id,
            asset=outputs[0].asset if outputs else "",
            direction="NO_TRADE",
            final_score=0.0,
            decision="NO_TRADE",
            agreement_pct=0.0,
            agent_contributions=[],
            regime=regime,
            regime_confidence=0.5,
            execution_mode="WATCH",
            trading_profile=profile,
        )


# Singleton
consensus_engine = ConsensusEngine()
