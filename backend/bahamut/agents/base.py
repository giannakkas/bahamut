from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID
import asyncio
import structlog

from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base class for all Bahamut.AI agents."""

    agent_id: str
    display_name: str
    required_features: list[str] = []
    timeout_seconds: int = 10

    @abstractmethod
    async def analyze(
        self, request: SignalCycleRequest, features: dict
    ) -> AgentOutputSchema:
        """Produce independent analysis. Must complete within timeout."""
        ...

    @abstractmethod
    async def respond_to_challenge(
        self, challenge: ChallengeRequest, original_output: AgentOutputSchema
    ) -> ChallengeResponseSchema:
        """Respond to a challenge from another agent or Supervisor."""
        ...

    async def run_with_timeout(
        self, request: SignalCycleRequest, features: dict
    ) -> AgentOutputSchema:
        """Run analysis with timeout protection."""
        start = datetime.now(timezone.utc)
        try:
            output = await asyncio.wait_for(
                self.analyze(request, features),
                timeout=self.timeout_seconds,
            )
            elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            logger.info(
                "agent_analysis_complete",
                agent_id=self.agent_id,
                cycle_id=str(request.cycle_id),
                bias=output.directional_bias,
                confidence=output.confidence,
                elapsed_ms=elapsed_ms,
            )
            return output
        except asyncio.TimeoutError:
            logger.warning(
                "agent_timeout",
                agent_id=self.agent_id,
                cycle_id=str(request.cycle_id),
                timeout_seconds=self.timeout_seconds,
            )
            return AgentOutputSchema(
                agent_id=self.agent_id,
                cycle_id=request.cycle_id,
                timestamp=datetime.now(timezone.utc),
                asset=request.asset,
                timeframe=request.timeframe,
                directional_bias="NO_TRADE",
                confidence=0.0,
                evidence=[Evidence(claim="Agent timed out", data_point="N/A", weight=0)],
                risk_notes=["AGENT_TIMEOUT: analysis could not complete in time"],
                meta={"timed_out": True},
            )

    def _make_output(
        self, request: SignalCycleRequest, bias: str, confidence: float,
        evidence: list[Evidence], risk_notes: list[str] = None,
        invalidation: list[str] = None, urgency: str = "NEXT_BAR",
        meta: dict = None,
    ) -> AgentOutputSchema:
        """Helper to construct standardized output."""
        return AgentOutputSchema(
            agent_id=self.agent_id,
            cycle_id=request.cycle_id,
            timestamp=datetime.now(timezone.utc),
            asset=request.asset,
            timeframe=request.timeframe,
            directional_bias=bias,
            confidence=round(max(0, min(1, confidence)), 3),
            evidence=evidence,
            risk_notes=risk_notes or [],
            invalidation_conditions=invalidation or [],
            regime_assessment=request.current_regime,
            urgency=urgency,
            meta=meta or {},
        )
