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
)

logger = structlog.get_logger()

# ── Base weights by asset class ──
BASE_WEIGHTS = {
    "fx": {
        "macro_agent": 0.18, "flow_agent": 0.15, "volatility_agent": 0.10,
        "options_agent": 0.05, "liquidity_agent": 0.12, "sentiment_agent": 0.10,
        "technical_agent": 0.15, "learning_agent": 0.05,
    },
    "indices": {
        "macro_agent": 0.15, "flow_agent": 0.12, "volatility_agent": 0.12,
        "options_agent": 0.15, "liquidity_agent": 0.10, "sentiment_agent": 0.10,
        "technical_agent": 0.12, "learning_agent": 0.04,
    },
    "commodities": {
        "macro_agent": 0.15, "flow_agent": 0.10, "volatility_agent": 0.10,
        "options_agent": 0.05, "liquidity_agent": 0.10, "sentiment_agent": 0.15,
        "technical_agent": 0.15, "learning_agent": 0.10,
    },
    "crypto": {
        "macro_agent": 0.08, "flow_agent": 0.10, "volatility_agent": 0.12,
        "options_agent": 0.05, "liquidity_agent": 0.15, "sentiment_agent": 0.20,
        "technical_agent": 0.15, "learning_agent": 0.05,
    },
    "bonds": {
        "macro_agent": 0.20, "flow_agent": 0.15, "volatility_agent": 0.10,
        "options_agent": 0.05, "liquidity_agent": 0.08, "sentiment_agent": 0.10,
        "technical_agent": 0.12, "learning_agent": 0.10,
    },
}

# ── Regime relevance multipliers ──
REGIME_RELEVANCE = {
    "RISK_OFF": {
        "macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 0.9,
        "technical_agent": 0.5, "flow_agent": 0.7, "options_agent": 0.6,
        "liquidity_agent": 0.7, "learning_agent": 0.5,
    },
    "RISK_ON": {
        "macro_agent": 0.8, "technical_agent": 1.0, "flow_agent": 1.0,
        "volatility_agent": 0.6, "sentiment_agent": 0.7, "options_agent": 0.7,
        "liquidity_agent": 0.8, "learning_agent": 0.7,
    },
    "HIGH_VOL": {
        "volatility_agent": 1.0, "options_agent": 1.0, "macro_agent": 0.7,
        "technical_agent": 0.5, "flow_agent": 0.6, "sentiment_agent": 0.8,
        "liquidity_agent": 0.8, "learning_agent": 0.5,
    },
    "LOW_VOL": {
        "technical_agent": 1.0, "liquidity_agent": 1.0, "options_agent": 0.8,
        "macro_agent": 0.6, "flow_agent": 0.8, "volatility_agent": 0.5,
        "sentiment_agent": 0.5, "learning_agent": 0.7,
    },
    "CRISIS": {
        "macro_agent": 1.0, "volatility_agent": 1.0, "sentiment_agent": 1.0,
        "technical_agent": 0.3, "flow_agent": 0.5, "options_agent": 0.5,
        "liquidity_agent": 0.6, "learning_agent": 0.3,
    },
    "TREND_CONTINUATION": {
        "technical_agent": 1.0, "flow_agent": 1.0, "macro_agent": 0.8,
        "volatility_agent": 0.6, "options_agent": 0.5, "sentiment_agent": 0.6,
        "liquidity_agent": 0.7, "learning_agent": 0.7,
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

        # Filter out timed-out agents and non-directional agents
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
        base_weights = BASE_WEIGHTS.get(asset_class, BASE_WEIGHTS["fx"])
        regime_rel = REGIME_RELEVANCE.get(regime, {k: 0.7 for k in base_weights})

        # ── Step 3: Calculate weighted score ──
        aligned_sum = 0.0
        opposed_penalty = 0.0
        total_weight = 0.0
        contributions = []

        for output in directional_outputs:
            aid = output.agent_id
            W = base_weights.get(aid, 0.1) * weight_overrides.get(aid, 1.0)
            T = trust_scores.get(aid, 1.0)
            R = regime_rel.get(aid, 0.7)
            C = float(output.confidence)

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
                "base_weight": W,
                "regime_relevance": R,
                "effective_contribution": round(contrib, 4),
            })

        if total_weight == 0:
            return self._no_trade_decision(agent_outputs, regime, trading_profile)

        raw_score = max(0.0, min(1.0, (aligned_sum - opposed_penalty) / total_weight))

        # ── Step 4: Agreement penalty ──
        dir_counts = Counter(
            o.directional_bias for o in directional_outputs
            if o.directional_bias != "NO_TRADE"
        )
        total_voting = sum(dir_counts.values())
        aligned_count = dir_counts.get(candidate_dir, 0)
        agreement_pct = aligned_count / total_voting if total_voting > 0 else 0

        thresholds = PROFILE_THRESHOLDS.get(trading_profile, PROFILE_THRESHOLDS["BALANCED"])
        min_agree_pct = thresholds["min_agreement"] / 9.0
        if agreement_pct < min_agree_pct:
            shortfall = min_agree_pct - agreement_pct
            raw_score = max(0.0, raw_score - shortfall * 2.0)

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
            exec_mode = "APPROVAL"
        else:
            exec_mode = "WATCH"

        # Dissenters
        dissenting = [
            {"agent_id": o.agent_id, "bias": o.directional_bias,
             "confidence": float(o.confidence), "evidence": o.evidence[0].claim if o.evidence else ""}
            for o in directional_outputs
            if o.directional_bias not in (candidate_dir, "NEUTRAL", "NO_TRADE")
        ]

        # Check risk agent
        risk_output = next((o for o in agent_outputs if o.agent_id == "risk_agent"), None)
        blocked = False
        block_reason = None
        risk_flags = []
        if risk_output:
            risk_flags = risk_output.meta.get("risk_flags", [])
            if not risk_output.meta.get("can_trade", True):
                blocked = True
                block_reason = f"Risk Agent veto: {', '.join(risk_flags)}"
                decision = "BLOCKED"
                exec_mode = "WATCH"

        cycle_id = directional_outputs[0].cycle_id if directional_outputs else uuid4()

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
            regime=regime,
            regime_confidence=0.8,
            risk_flags=risk_flags,
            blocked=blocked,
            block_reason=block_reason,
            execution_mode=exec_mode,
            trading_profile=trading_profile,
        )

    def _determine_direction(self, outputs: list[AgentOutputSchema]) -> str:
        counts = Counter(
            o.directional_bias for o in outputs
            if o.directional_bias not in ("NO_TRADE", "NEUTRAL")
        )
        if not counts:
            return "NO_TRADE"
        top_two = counts.most_common(2)
        if len(top_two) > 1 and top_two[0][1] == top_two[1][1]:
            return "NO_TRADE"  # tie
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
