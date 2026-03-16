from pydantic import BaseModel
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime


class Evidence(BaseModel):
    claim: str
    data_point: str
    weight: float = 0.5
    freshness_hours: float = 0.0


class AgentOutputSchema(BaseModel):
    agent_id: str
    cycle_id: UUID
    timestamp: datetime
    asset: str
    timeframe: str
    directional_bias: Literal["LONG", "SHORT", "NEUTRAL", "NO_TRADE"]
    confidence: float
    evidence: list[Evidence]
    risk_notes: list[str] = []
    invalidation_conditions: list[str] = []
    regime_assessment: str = ""
    urgency: Literal["IMMEDIATE", "NEXT_BAR", "PATIENT"] = "NEXT_BAR"
    meta: dict = {}


class ChallengeRequest(BaseModel):
    challenge_id: UUID
    cycle_id: UUID
    challenger: str
    target_agent: str
    challenge_type: str
    trigger_reason: str
    context: dict = {}


class ChallengeResponseSchema(BaseModel):
    challenge_id: UUID
    challenger: str
    target_agent: str
    challenge_type: str
    response: Literal["ACCEPT", "REJECT", "PARTIAL", "VETO", "ABSTAIN"]
    revised_confidence: Optional[float] = None
    revised_bias: Optional[str] = None
    justification: str = ""


class ConflictMap(BaseModel):
    cycle_id: UUID
    total_agents_responded: int
    timed_out_agents: list[str] = []
    direction_counts: dict[str, int]
    agreement_pct: float
    contradictions: list[dict] = []
    unanimous: bool = False


class TradePlanSchema(BaseModel):
    entry_price: Optional[float] = None
    entry_type: Literal["MARKET", "LIMIT", "STOP"] = "MARKET"
    stop_loss: float
    take_profit: float
    position_size_pct: float
    risk_reward_ratio: float
    max_hold_duration: str = "4H"
    invalidation_price: float


class ConsensusDecisionSchema(BaseModel):
    consensus_id: UUID
    cycle_id: UUID
    asset: str
    direction: Literal["LONG", "SHORT", "NO_TRADE"]
    final_score: float
    decision: str
    agreement_pct: float
    agent_contributions: list[dict]
    dissenting_agents: list[dict] = []
    challenges: list[dict] = []
    regime: str
    regime_confidence: float
    risk_flags: list[str] = []
    blocked: bool = False
    block_reason: Optional[str] = None
    trade_plan: Optional[TradePlanSchema] = None
    explanation: str = ""
    execution_mode: Literal["AUTO", "APPROVAL", "WATCH"] = "WATCH"
    trading_profile: str = "BALANCED"


class SignalCycleRequest(BaseModel):
    cycle_id: UUID
    asset: str
    asset_class: str
    timeframe: str
    triggered_by: str
    current_regime: str
    regime_confidence: float = 0.5
    trading_profile: str = "BALANCED"
