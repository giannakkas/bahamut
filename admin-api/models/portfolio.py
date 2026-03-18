from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class KillSwitchState(BaseModel):
    active: bool
    reason: str | None
    last_triggered: str


class SafeModeState(BaseModel):
    active: bool
    level: int


class ReadinessComponents(BaseModel):
    data: float
    model: float
    market: float


class ReadinessState(BaseModel):
    score: float
    grade: str
    components: ReadinessComponents


class ConfidenceState(BaseModel):
    score: float
    trend: Literal["rising", "stable", "falling"]
    history: list[float]


class SystemSummary(BaseModel):
    """Matches frontend SystemSummary exactly."""

    kill_switch: KillSwitchState
    safe_mode: SafeModeState
    readiness: ReadinessState
    confidence: ConfidenceState
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    active_constraints: int
    portfolio_value: float
    daily_pnl: float
    daily_pnl_pct: float
    open_positions: int
    agents_active: int
    last_cycle: str


class RiskContributor(BaseModel):
    asset: str
    risk: float
    weight: float
    contribution_pct: float


class ScenarioResult(BaseModel):
    name: str
    probability: float
    impact: float
    color: str


class MarginalRiskData(BaseModel):
    """Matches frontend MarginalRiskData exactly."""

    total_risk: float
    expected_return: float
    quality_ratio: float
    contributors: list[RiskContributor]
    scenarios: list[ScenarioResult]


class KillSwitchToggle(BaseModel):
    active: bool


class LearningPattern(BaseModel):
    """Matches frontend LearningPattern exactly."""

    pattern: str
    frequency: int
    confidence: float
    win_rate: float
    last_seen: str


class Alert(BaseModel):
    """Matches frontend Alert exactly."""

    id: int
    type: Literal["info", "warning", "error", "critical"]
    message: str
    timestamp: str
    dismissed: bool


class AISuggestion(BaseModel):
    """Matches frontend AISuggestion exactly."""

    key: str
    current: float
    suggested: float
    reason: str
