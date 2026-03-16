"""
Bahamut.AI Agent Orchestrator
Runs the full 7-round consensus cycle: Independent Analysis -> Conflict Detection ->
Challenge Routing -> Final Lock -> Consensus Calculation -> Execution Routing.
"""
import asyncio
import time
from uuid import uuid4
from datetime import datetime, timezone
from collections import Counter
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from bahamut.agents.schemas import (
    SignalCycleRequest, AgentOutputSchema, ChallengeRequest,
    ChallengeResponseSchema, ConflictMap,
)
from bahamut.agents.base import BaseAgent
from bahamut.agents.technical_agent import TechnicalAgent
from bahamut.agents.macro_agent import MacroAgent
from bahamut.agents.risk_agent import RiskAgent
from bahamut.consensus.engine import consensus_engine
from bahamut.consensus.trust_store import trust_store

logger = structlog.get_logger()

# ── Agent Registry ──
DIRECTIONAL_AGENTS: dict[str, BaseAgent] = {
    "technical_agent": TechnicalAgent(),
    "macro_agent": MacroAgent(),
    # Future agents will be added here as implemented:
    # "flow_agent": FlowAgent(),
    # "volatility_agent": VolatilityAgent(),
    # "options_agent": OptionsGammaAgent(),
    # "liquidity_agent": LiquidityStructureAgent(),
    # "sentiment_agent": SentimentNarrativeAgent(),
    # "learning_agent": LearningAgentImpl(),
}

RISK_AGENT = RiskAgent()

# ── Feature routing per agent ──
AGENT_FEATURE_MAP = {
    "technical_agent": ["indicators", "ohlcv"],
    "macro_agent": ["macro", "volatility", "regime"],
    "flow_agent": ["flow", "currency_strength"],
    "volatility_agent": ["volatility", "ohlcv"],
    "options_agent": ["options", "ohlcv"],
    "liquidity_agent": ["ohlcv", "volume_profile"],
    "sentiment_agent": ["news", "sentiment"],
    "learning_agent": ["performance_metrics"],
}


class AgentOrchestrator:
    """Orchestrates the full multi-agent consensus cycle."""

    async def run_cycle(
        self,
        asset: str,
        asset_class: str,
        timeframe: str,
        regime: str,
        regime_confidence: float,
        trading_profile: str,
        features: dict,
        portfolio_state: dict = None,
        triggered_by: str = "SCHEDULE",
    ) -> dict:
        """
        Execute a complete signal cycle.
        Returns the full cycle result including consensus decision.
        """
        cycle_id = uuid4()
        start_time = time.time()

        request = SignalCycleRequest(
            cycle_id=cycle_id,
            asset=asset,
            asset_class=asset_class,
            timeframe=timeframe,
            triggered_by=triggered_by,
            current_regime=regime,
            regime_confidence=regime_confidence,
            trading_profile=trading_profile,
        )

        logger.info(
            "signal_cycle_started",
            cycle_id=str(cycle_id),
            asset=asset,
            timeframe=timeframe,
            regime=regime,
            profile=trading_profile,
        )

        # ══════════════════════════════════════
        # ROUND 1: Independent Analysis
        # ══════════════════════════════════════
        agent_features = self._route_features(features)

        tasks = []
        for agent_id, agent in DIRECTIONAL_AGENTS.items():
            agent_feat = agent_features.get(agent_id, {})
            tasks.append(agent.run_with_timeout(request, agent_feat))

        directional_outputs = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_outputs: list[AgentOutputSchema] = []
        for output in directional_outputs:
            if isinstance(output, AgentOutputSchema):
                valid_outputs.append(output)
            else:
                logger.error("agent_exception", error=str(output))

        # Run Risk Agent
        risk_features = {
            "portfolio": portfolio_state or {"open_trade_count": 0, "net_exposure_pct": 0, "max_correlation": 0},
            "drawdown": portfolio_state.get("drawdown", {"daily": 0, "weekly": 0}) if portfolio_state else {"daily": 0, "weekly": 0},
        }
        risk_output = await RISK_AGENT.run_with_timeout(request, risk_features)

        all_outputs = valid_outputs + [risk_output]

        # ══════════════════════════════════════
        # ROUND 2: Conflict Detection
        # ══════════════════════════════════════
        conflict_map = self._detect_conflicts(cycle_id, valid_outputs)

        # ══════════════════════════════════════
        # ROUND 3: Challenge Routing
        # ══════════════════════════════════════
        challenges = await self._route_challenges(
            cycle_id, valid_outputs, risk_output, conflict_map
        )

        # Apply challenge results to outputs
        for challenge_resp in challenges:
            if challenge_resp.response == "PARTIAL" and challenge_resp.revised_confidence is not None:
                for output in valid_outputs:
                    if output.agent_id == challenge_resp.target_agent:
                        output.confidence = challenge_resp.revised_confidence
            elif challenge_resp.response == "ACCEPT" and challenge_resp.revised_bias:
                for output in valid_outputs:
                    if output.agent_id == challenge_resp.target_agent:
                        output.directional_bias = challenge_resp.revised_bias

        # ══════════════════════════════════════
        # ROUNDS 4-5: Lock & Consensus
        # ══════════════════════════════════════
        trust_scores = trust_store.get_scores_for_context(regime, asset_class, timeframe)

        # Load weight overrides from profile
        from bahamut.auth.router import PROFILE_DEFAULTS
        profile_config = PROFILE_DEFAULTS.get(trading_profile, {})
        weight_overrides = profile_config.get("weight_overrides", {})

        decision = consensus_engine.calculate(
            agent_outputs=all_outputs,
            asset_class=asset_class,
            regime=regime,
            trading_profile=trading_profile,
            trust_scores=trust_scores,
            weight_overrides=weight_overrides,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "signal_cycle_completed",
            cycle_id=str(cycle_id),
            asset=asset,
            direction=decision.direction,
            score=decision.final_score,
            decision=decision.decision,
            agreement=decision.agreement_pct,
            elapsed_ms=elapsed_ms,
        )

        return {
            "cycle_id": str(cycle_id),
            "decision": decision.model_dump(),
            "agent_outputs": [o.model_dump() for o in all_outputs],
            "challenges": [c.model_dump() for c in challenges],
            "conflict_map": conflict_map.model_dump(),
            "elapsed_ms": elapsed_ms,
        }

    def _route_features(self, features: dict) -> dict[str, dict]:
        """Route feature subsets to each agent based on AGENT_FEATURE_MAP."""
        routed = {}
        for agent_id, required_keys in AGENT_FEATURE_MAP.items():
            agent_features = {}
            for key in required_keys:
                if key in features:
                    agent_features[key] = features[key]
            routed[agent_id] = agent_features
        return routed

    def _detect_conflicts(
        self, cycle_id, outputs: list[AgentOutputSchema]
    ) -> ConflictMap:
        """Round 2: Identify agreement, disagreement, and contradictions."""
        dir_counts = Counter(
            o.directional_bias for o in outputs
            if o.directional_bias not in ("NO_TRADE",)
        )
        total = len([o for o in outputs if o.directional_bias != "NO_TRADE"])
        majority = dir_counts.most_common(1)[0][1] if dir_counts else 0
        agreement_pct = majority / total if total > 0 else 0

        # Find contradictions (opposing high-confidence agents)
        contradictions = []
        high_conf = [o for o in outputs if o.confidence > 0.6 and o.directional_bias in ("LONG", "SHORT")]
        for i, a in enumerate(high_conf):
            for b in high_conf[i + 1:]:
                if a.directional_bias != b.directional_bias:
                    severity = "HIGH" if min(a.confidence, b.confidence) > 0.7 else "MEDIUM"
                    contradictions.append({
                        "agent_a": a.agent_id,
                        "agent_b": b.agent_id,
                        "agent_a_bias": a.directional_bias,
                        "agent_b_bias": b.directional_bias,
                        "severity": severity,
                    })

        timed_out = [o.agent_id for o in outputs if o.meta.get("timed_out")]

        return ConflictMap(
            cycle_id=cycle_id,
            total_agents_responded=len(outputs) - len(timed_out),
            timed_out_agents=timed_out,
            direction_counts=dict(dir_counts),
            agreement_pct=round(agreement_pct, 3),
            contradictions=contradictions,
            unanimous=len(dir_counts) == 1 and total > 1,
        )

    async def _route_challenges(
        self,
        cycle_id,
        directional_outputs: list[AgentOutputSchema],
        risk_output: AgentOutputSchema,
        conflict_map: ConflictMap,
    ) -> list[ChallengeResponseSchema]:
        """Round 3: Route targeted challenges based on rule table."""
        challenges = []

        # Risk Agent challenges all directional agents
        for output in directional_outputs:
            if output.directional_bias in ("LONG", "SHORT"):
                challenge = ChallengeRequest(
                    challenge_id=uuid4(),
                    cycle_id=cycle_id,
                    challenger="risk_agent",
                    target_agent=output.agent_id,
                    challenge_type="RISK_CHECK",
                    trigger_reason=f"Standard risk check for {output.directional_bias} signal",
                )
                response = await DIRECTIONAL_AGENTS[output.agent_id].respond_to_challenge(
                    challenge, output
                ) if output.agent_id in DIRECTIONAL_AGENTS else ChallengeResponseSchema(
                    challenge_id=challenge.challenge_id,
                    challenger="risk_agent",
                    target_agent=output.agent_id,
                    challenge_type="RISK_CHECK",
                    response="ACCEPT",
                    justification="Default accept",
                )
                challenges.append(response)

        # Macro vs Technical conflict
        macro_out = next((o for o in directional_outputs if o.agent_id == "macro_agent"), None)
        tech_out = next((o for o in directional_outputs if o.agent_id == "technical_agent"), None)

        if (macro_out and tech_out and
                macro_out.directional_bias != tech_out.directional_bias and
                macro_out.directional_bias in ("LONG", "SHORT") and
                tech_out.directional_bias in ("LONG", "SHORT") and
                macro_out.confidence > 0.6 and tech_out.confidence > 0.6):

            challenge = ChallengeRequest(
                challenge_id=uuid4(),
                cycle_id=cycle_id,
                challenger="macro_agent",
                target_agent="technical_agent",
                challenge_type="REGIME_OVERRIDE",
                trigger_reason=f"Macro ({macro_out.directional_bias}) conflicts with Technical ({tech_out.directional_bias})",
            )
            response = await DIRECTIONAL_AGENTS["technical_agent"].respond_to_challenge(
                challenge, tech_out
            )
            challenges.append(response)

        return challenges


# Singleton
orchestrator = AgentOrchestrator()
