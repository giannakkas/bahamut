"""
Bahamut.AI Agent Orchestrator
Runs the full consensus cycle with real market data from OANDA.
"""
import asyncio
import time
from uuid import uuid4
from datetime import datetime, timezone
from collections import Counter

import structlog

from bahamut.agents.schemas import (
    SignalCycleRequest, AgentOutputSchema, ChallengeRequest,
    ChallengeResponseSchema, ConflictMap,
)
from bahamut.agents.base import BaseAgent
from bahamut.agents.technical_agent import TechnicalAgent
from bahamut.agents.macro_agent import MacroAgent
from bahamut.agents.risk_agent import RiskAgent
from bahamut.agents.volatility_agent import VolatilityAgent
from bahamut.agents.sentiment_agent import SentimentAgent
from bahamut.agents.liquidity_agent import LiquidityAgent
from bahamut.consensus.engine import consensus_engine
from bahamut.consensus.trust_store import trust_store
from bahamut.consensus.disagreement import disagreement_engine
from bahamut.consensus.weights import weight_resolver
from bahamut.ingestion.market_data import market_data

logger = structlog.get_logger()

# ── Agent Registry ──
DIRECTIONAL_AGENTS: dict[str, BaseAgent] = {
    "technical_agent": TechnicalAgent(),
    "macro_agent": MacroAgent(),
    "volatility_agent": VolatilityAgent(),
    "sentiment_agent": SentimentAgent(),
    "liquidity_agent": LiquidityAgent(),
}

RISK_AGENT = RiskAgent()


class AgentOrchestrator:

    async def run_cycle(
        self,
        asset: str,
        asset_class: str,
        timeframe: str,
        regime: str = "RISK_ON",
        regime_confidence: float = 0.78,
        trading_profile: str = "BALANCED",
        features: dict = None,
        portfolio_state: dict = None,
        triggered_by: str = "SCHEDULE",
    ) -> dict:
        cycle_id = uuid4()
        start_time = time.time()

        # ═════════════════════════════════════
        # FETCH REAL MARKET DATA
        # ═════════════════════════════════════
        if features is None:
            features = await market_data.get_features_for_asset(asset, timeframe)

        if portfolio_state is None:
            portfolio_state = await market_data.get_account_state()

        data_source = features.get("source", "unknown")

        # ═════════════════════════════════════
        # AUTO-DETECT REGIME
        # ═════════════════════════════════════
        if regime == "RISK_ON" and features.get("indicators"):
            try:
                from bahamut.features.regime import detect_regime_from_features
                detected = detect_regime_from_features(features)
                regime = detected.primary_regime
                regime_confidence = detected.confidence
            except Exception as e:
                logger.warning("regime_detect_failed", error=str(e))

        request = SignalCycleRequest(
            cycle_id=cycle_id, asset=asset, asset_class=asset_class,
            timeframe=timeframe, triggered_by=triggered_by,
            current_regime=regime, regime_confidence=regime_confidence,
            trading_profile=trading_profile,
        )

        logger.info("signal_cycle_started", cycle_id=str(cycle_id),
                     asset=asset, timeframe=timeframe, regime=regime)

        # ═════════════════════════════════════
        # ROUND 1: Independent Analysis
        # ═════════════════════════════════════
        tasks = []
        for agent_id, agent in DIRECTIONAL_AGENTS.items():
            tasks.append(agent.run_with_timeout(request, features))

        directional_outputs = await asyncio.gather(*tasks, return_exceptions=True)

        valid_outputs: list[AgentOutputSchema] = []
        for output in directional_outputs:
            if isinstance(output, AgentOutputSchema):
                valid_outputs.append(output)
            else:
                logger.error("agent_exception", error=str(output))

        # Run Risk Agent
        risk_features = {
            "portfolio": portfolio_state,
            "drawdown": portfolio_state.get("drawdown", {"daily": 0, "weekly": 0}),
        }
        risk_output = await RISK_AGENT.run_with_timeout(request, risk_features)
        all_outputs = valid_outputs + [risk_output]

        # ═════════════════════════════════════
        # ROUND 2: Conflict Detection
        # ═════════════════════════════════════
        conflict_map = self._detect_conflicts(cycle_id, valid_outputs)

        # ═════════════════════════════════════
        # ROUND 3: Challenge Routing
        # ═════════════════════════════════════
        challenges = await self._route_challenges(cycle_id, valid_outputs, risk_output, conflict_map)

        for ch_resp in challenges:
            if ch_resp.response == "PARTIAL" and ch_resp.revised_confidence is not None:
                for output in valid_outputs:
                    if output.agent_id == ch_resp.target_agent:
                        output.confidence = ch_resp.revised_confidence
            elif ch_resp.response == "ACCEPT" and ch_resp.revised_bias:
                for output in valid_outputs:
                    if output.agent_id == ch_resp.target_agent:
                        output.directional_bias = ch_resp.revised_bias

        # ═════════════════════════════════════
        # ROUNDS 4-7: Consensus
        # ═════════════════════════════════════

        # Compute disagreement BEFORE consensus
        disagreement_metrics = disagreement_engine.calculate(
            directional_outputs=valid_outputs,
            risk_output=risk_output,
            challenges=challenges,
            trading_profile=trading_profile,
        )

        trust_scores = trust_store.get_scores_for_context(regime, asset_class, timeframe)

        from bahamut.auth.router import PROFILE_DEFAULTS
        profile_config = PROFILE_DEFAULTS.get(trading_profile, {})
        profile_overrides = profile_config.get("weight_overrides", {})

        # Dynamic weight resolution
        resolved_weights = weight_resolver.resolve_weights(
            asset_class=asset_class, regime=regime, timeframe=timeframe,
            trust_scores=trust_scores, profile_weight_overrides=profile_overrides,
        )

        decision = consensus_engine.calculate(
            agent_outputs=all_outputs, asset_class=asset_class,
            regime=regime, trading_profile=trading_profile,
            trust_scores=trust_scores, resolved_weights=resolved_weights,
            disagreement_metrics=disagreement_metrics,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info("signal_cycle_completed", cycle_id=str(cycle_id),
                     asset=asset, direction=decision.direction,
                     score=decision.final_score, decision=decision.decision,
                     agreement=decision.agreement_pct, elapsed_ms=elapsed_ms,
                     data_source=data_source, agents_responded=len(valid_outputs),
                     disagreement=disagreement_metrics.disagreement_index,
                     exec_gate=disagreement_metrics.execution_gate)

        # ═════════════════════════════════════
        # PAPER TRADING HOOK — auto-execute demo trades
        # ═════════════════════════════════════
        try:
            from bahamut.paper_trading.tasks import on_signal_complete

            agent_votes = {}
            for o in all_outputs:
                agent_votes[o.agent_id.replace("_agent", "")] = {
                    "direction": o.directional_bias,
                    "confidence": o.confidence,
                    "score": o.score if hasattr(o, "score") else 0.0,
                }

            current_price = features.get("indicators", {}).get("close", 0)
            atr = features.get("indicators", {}).get("atr_14", 0) or (current_price * 0.01)

            if decision.direction in ("LONG", "SHORT") and current_price > 0:
                logger.info("paper_trading_hook_firing",
                            asset=asset, direction=decision.direction,
                            score=decision.final_score, label=decision.decision,
                            price=current_price, atr=atr)
                on_signal_complete.delay(
                    asset=asset,
                    direction=decision.direction,
                    consensus_score=decision.final_score,
                    signal_label=decision.decision,
                    entry_price=current_price,
                    atr=atr,
                    agent_votes=agent_votes,
                    cycle_id=str(cycle_id),
                    execution_gate=disagreement_metrics.execution_gate,
                    disagreement_index=disagreement_metrics.disagreement_index,
                )
            else:
                logger.info("paper_trading_hook_skipped",
                            asset=asset, direction=decision.direction,
                            score=decision.final_score, price=current_price)
        except Exception as e:
            logger.error("paper_trading_hook_failed", error=str(e), traceback=True)

        return {
            "cycle_id": str(cycle_id),
            "decision": decision.model_dump(),
            "agent_outputs": [o.model_dump() for o in all_outputs],
            "challenges": [c.model_dump() for c in challenges],
            "conflict_map": conflict_map.model_dump(),
            "disagreement": disagreement_metrics.model_dump(),
            "elapsed_ms": elapsed_ms,
            "data_source": data_source,
            "market_price": features.get("indicators", {}).get("close"),
        }

    def _detect_conflicts(self, cycle_id, outputs):
        dir_counts = Counter(
            o.directional_bias for o in outputs if o.directional_bias != "NO_TRADE"
        )
        total = len([o for o in outputs if o.directional_bias != "NO_TRADE"])
        majority = dir_counts.most_common(1)[0][1] if dir_counts else 0
        agreement_pct = majority / total if total > 0 else 0

        contradictions = []
        high_conf = [o for o in outputs if o.confidence > 0.6 and o.directional_bias in ("LONG", "SHORT")]
        for i, a in enumerate(high_conf):
            for b_item in high_conf[i + 1:]:
                if a.directional_bias != b_item.directional_bias:
                    contradictions.append({
                        "agent_a": a.agent_id, "agent_b": b_item.agent_id,
                        "agent_a_bias": a.directional_bias,
                        "agent_b_bias": b_item.directional_bias,
                        "severity": "HIGH" if min(a.confidence, b_item.confidence) > 0.7 else "MEDIUM",
                    })

        return ConflictMap(
            cycle_id=cycle_id,
            total_agents_responded=len(outputs),
            timed_out_agents=[o.agent_id for o in outputs if o.meta.get("timed_out")],
            direction_counts=dict(dir_counts),
            agreement_pct=round(agreement_pct, 3),
            contradictions=contradictions,
            unanimous=len(dir_counts) == 1 and total > 1,
        )

    async def _route_challenges(self, cycle_id, directional_outputs, risk_output, conflict_map):
        challenges = []

        # Risk checks all directional agents
        for output in directional_outputs:
            if output.directional_bias in ("LONG", "SHORT"):
                ch = ChallengeRequest(
                    challenge_id=uuid4(), cycle_id=cycle_id,
                    challenger="risk_agent", target_agent=output.agent_id,
                    challenge_type="RISK_CHECK",
                    trigger_reason=f"Risk check for {output.directional_bias}",
                )
                if output.agent_id in DIRECTIONAL_AGENTS:
                    resp = await DIRECTIONAL_AGENTS[output.agent_id].respond_to_challenge(ch, output)
                    challenges.append(resp)

        # Macro vs Technical
        macro = next((o for o in directional_outputs if o.agent_id == "macro_agent"), None)
        tech = next((o for o in directional_outputs if o.agent_id == "technical_agent"), None)
        if (macro and tech and
                macro.directional_bias != tech.directional_bias and
                macro.directional_bias in ("LONG", "SHORT") and
                tech.directional_bias in ("LONG", "SHORT") and
                macro.confidence > 0.6 and tech.confidence > 0.6):
            ch = ChallengeRequest(
                challenge_id=uuid4(), cycle_id=cycle_id,
                challenger="macro_agent", target_agent="technical_agent",
                challenge_type="REGIME_OVERRIDE",
                trigger_reason=f"Macro ({macro.directional_bias}) vs Technical ({tech.directional_bias})",
            )
            resp = await DIRECTIONAL_AGENTS["technical_agent"].respond_to_challenge(ch, tech)
            challenges.append(resp)

        # Volatility challenges Technical in high-vol
        vol = next((o for o in directional_outputs if o.agent_id == "volatility_agent"), None)
        if vol and vol.meta.get("vol_score", 0) < -10 and tech and tech.confidence > 0.5:
            ch = ChallengeRequest(
                challenge_id=uuid4(), cycle_id=cycle_id,
                challenger="volatility_agent", target_agent="technical_agent",
                challenge_type="VOL_REJECT",
                trigger_reason="High volatility environment - timing risk",
            )
            resp = await DIRECTIONAL_AGENTS["technical_agent"].respond_to_challenge(ch, tech)
            challenges.append(resp)

        return challenges


orchestrator = AgentOrchestrator()
