import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, Text, DateTime, ForeignKey,
    Numeric, ARRAY, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET, BYTEA
from sqlalchemy.orm import relationship
from bahamut.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return uuid.uuid4()


# ═══════════════════════════════════════
# WORKSPACES & USERS
# ═══════════════════════════════════════

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    plan = Column(String(50), default="starter")
    max_users = Column(Integer, default=5)
    max_assets = Column(Integer, default=10)
    auto_trade_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    users = relationship("User", back_populates="workspace")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="trader")
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime(timezone=True))

    workspace = relationship("Workspace", back_populates="users")
    trading_profiles = relationship("TradingProfile", back_populates="user")
    trades = relationship("Trade", back_populates="user")


# ═══════════════════════════════════════
# TRADING PROFILES
# ═══════════════════════════════════════

class TradingProfile(Base):
    __tablename__ = "trading_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=False)

    # Consensus thresholds
    strong_signal_threshold = Column(Numeric(4, 3), nullable=False)
    signal_threshold = Column(Numeric(4, 3), nullable=False)
    weak_signal_threshold = Column(Numeric(4, 3), nullable=False)
    min_agent_agreement = Column(Integer, nullable=False)
    min_individual_confidence = Column(Numeric(3, 2), nullable=False)
    challenge_rounds = Column(Integer, nullable=False, default=1)

    # Risk limits
    max_daily_drawdown = Column(Numeric(5, 4), nullable=False)
    max_weekly_drawdown = Column(Numeric(5, 4), nullable=False)
    max_total_drawdown = Column(Numeric(5, 4), nullable=False)
    max_concurrent_trades = Column(Integer, nullable=False)
    max_leverage = Column(Numeric(5, 2), nullable=False)
    max_single_position_pct = Column(Numeric(5, 4), nullable=False)
    max_correlated_exposure = Column(Numeric(5, 4), nullable=False)
    correlation_threshold = Column(Numeric(3, 2), nullable=False)

    # Execution params
    vix_freeze_threshold = Column(Numeric(5, 2), nullable=False)
    event_freeze_hours = Column(Integer, nullable=False)
    stop_loss_atr_multiple = Column(Numeric(4, 2), nullable=False)
    take_profit_atr_multiple = Column(Numeric(4, 2), nullable=False)
    entry_type = Column(String(20), nullable=False)
    require_pullback = Column(Boolean, default=False)

    # Regime
    allowed_regimes = Column(ARRAY(Text), nullable=False)
    auto_downgrade_on_crisis = Column(Boolean, default=False)

    # Learning sensitivity
    streak_tighten_after = Column(Integer, nullable=False, default=3)
    streak_loosen_after = Column(Integer, nullable=False, default=5)

    # Weight overrides
    weight_overrides = Column(JSONB, default={})

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="trading_profiles")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_profile_name"),
    )


class AutoTradePermission(Base):
    __tablename__ = "auto_trade_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    asset = Column(String(20), nullable=False)
    profile_name = Column(String(50), nullable=False)
    enabled = Column(Boolean, default=False)
    max_daily_trades = Column(Integer, default=3)
    confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "asset", "profile_name", name="uq_auto_trade_perm"),
    )


# ═══════════════════════════════════════
# ASSETS
# ═══════════════════════════════════════

class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    symbol = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    asset_class = Column(String(20), nullable=False)
    exchange = Column(String(50))
    base_currency = Column(String(10))
    quote_currency = Column(String(10))
    pip_size = Column(Numeric(10, 8))
    min_lot_size = Column(Numeric(10, 4))
    trading_hours = Column(JSONB)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════
# SIGNAL CYCLES & AGENT OUTPUTS
# ═══════════════════════════════════════

class SignalCycle(Base):
    __tablename__ = "signal_cycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    timeframe = Column(String(5), nullable=False)
    triggered_by = Column(String(30), nullable=False)
    regime_at_start = Column(String(50), nullable=False)
    trading_profile = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)
    error_message = Column(Text)

    agent_outputs = relationship("AgentOutput", back_populates="cycle")
    consensus_decision = relationship("ConsensusDecision", back_populates="cycle", uselist=False)
    challenges = relationship("AgentChallenge", back_populates="cycle")


class AgentOutput(Base):
    __tablename__ = "agent_outputs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("signal_cycles.id"), nullable=False)
    agent_id = Column(String(50), nullable=False)
    directional_bias = Column(String(20), nullable=False)
    confidence = Column(Numeric(4, 3), nullable=False)
    evidence = Column(JSONB, nullable=False)
    risk_notes = Column(ARRAY(Text))
    invalidation_conditions = Column(ARRAY(Text))
    regime_assessment = Column(String(100))
    urgency = Column(String(20))
    meta = Column(JSONB, default={})
    response_time_ms = Column(Integer)
    timed_out = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    cycle = relationship("SignalCycle", back_populates="agent_outputs")

    __table_args__ = (
        UniqueConstraint("cycle_id", "agent_id", name="uq_cycle_agent"),
        Index("idx_agent_outputs_cycle", "cycle_id"),
        Index("idx_agent_outputs_agent_time", "agent_id", "created_at"),
    )


class AgentChallenge(Base):
    __tablename__ = "agent_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("signal_cycles.id"), nullable=False)
    challenger_id = Column(String(50), nullable=False)
    target_agent_id = Column(String(50), nullable=False)
    challenge_type = Column(String(50), nullable=False)
    trigger_reason = Column(Text, nullable=False)
    response = Column(String(20), nullable=False)
    revised_confidence = Column(Numeric(4, 3))
    revised_bias = Column(String(20))
    justification = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    cycle = relationship("SignalCycle", back_populates="challenges")


class ConsensusDecision(Base):
    __tablename__ = "consensus_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("signal_cycles.id"), unique=True, nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    direction = Column(String(20), nullable=False)
    final_score = Column(Numeric(5, 4), nullable=False)
    decision = Column(String(30), nullable=False)
    agreement_pct = Column(Numeric(4, 3), nullable=False)
    agent_contributions = Column(JSONB, nullable=False)
    dissenting_agents = Column(JSONB)
    regime = Column(String(50), nullable=False)
    regime_confidence = Column(Numeric(4, 3))
    risk_flags = Column(ARRAY(Text))
    blocked = Column(Boolean, default=False)
    block_reason = Column(Text)
    trade_plan = Column(JSONB)
    explanation = Column(Text)
    execution_mode = Column(String(20))
    trading_profile = Column(String(50), nullable=False)
    profile_overrides_applied = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    cycle = relationship("SignalCycle", back_populates="consensus_decision")

    __table_args__ = (
        Index("idx_consensus_asset_time", "asset_id", "created_at"),
    )


# ═══════════════════════════════════════
# TRADES
# ═══════════════════════════════════════

class Trade(Base):
    __tablename__ = "trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    consensus_id = Column(UUID(as_uuid=True), ForeignKey("consensus_decisions.id"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)

    direction = Column(String(10), nullable=False)
    position_size = Column(Numeric(18, 8), nullable=False)
    position_pct = Column(Numeric(5, 4), nullable=False)
    leverage_used = Column(Numeric(5, 2))

    planned_entry = Column(Numeric(18, 8))
    actual_entry = Column(Numeric(18, 8))
    stop_loss = Column(Numeric(18, 8), nullable=False)
    take_profit = Column(Numeric(18, 8), nullable=False)
    actual_exit = Column(Numeric(18, 8))
    invalidation = Column(Numeric(18, 8))

    pnl_absolute = Column(Numeric(18, 4))
    pnl_pct = Column(Numeric(8, 4))
    max_favorable = Column(Numeric(18, 8))
    max_adverse = Column(Numeric(18, 8))
    risk_reward_planned = Column(Numeric(6, 2))
    risk_reward_actual = Column(Numeric(6, 2))

    execution_mode = Column(String(20), nullable=False)
    trading_profile = Column(String(50), nullable=False)
    slippage_bps = Column(Numeric(8, 2))
    fill_quality = Column(Numeric(4, 3))

    regime_at_entry = Column(String(50), nullable=False)
    regime_at_exit = Column(String(50))
    vix_at_entry = Column(Numeric(8, 2))
    vix_at_exit = Column(Numeric(8, 2))
    consensus_score = Column(Numeric(5, 4), nullable=False)
    agent_agreement = Column(Numeric(4, 3), nullable=False)
    nearest_event = Column(String(200))
    event_distance_hours = Column(Numeric(6, 1))

    status = Column(String(20), nullable=False, default="pending")
    opened_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    hold_duration_minutes = Column(Integer)
    close_reason = Column(String(50))

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="trades")

    __table_args__ = (
        Index("idx_trades_user_status", "user_id", "status"),
        Index("idx_trades_asset_time", "asset_id", "opened_at"),
    )


class TradeApproval(Base):
    __tablename__ = "trade_approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    trade_id = Column(UUID(as_uuid=True), ForeignKey("trades.id"), nullable=False)
    consensus_id = Column(UUID(as_uuid=True), ForeignKey("consensus_decisions.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(String(20), nullable=False)
    snooze_until = Column(DateTime(timezone=True))
    modifications = Column(JSONB)
    rejection_reason = Column(Text)
    feedback = Column(Text)
    decision_latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════
# TRUST SCORES
# ═══════════════════════════════════════

class TrustScore(Base):
    __tablename__ = "trust_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    agent_id = Column(String(50), nullable=False)
    dimension = Column(String(100), nullable=False)
    score = Column(Numeric(5, 4), nullable=False, default=1.0)
    sample_count = Column(Integer, nullable=False, default=0)
    last_trade_id = Column(UUID(as_uuid=True), ForeignKey("trades.id"))
    decay_applied = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("agent_id", "dimension", name="uq_agent_dimension"),
        Index("idx_trust_agent", "agent_id"),
    )


class TrustScoreHistory(Base):
    __tablename__ = "trust_score_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    agent_id = Column(String(50), nullable=False)
    dimension = Column(String(100), nullable=False)
    old_score = Column(Numeric(5, 4), nullable=False)
    new_score = Column(Numeric(5, 4), nullable=False)
    change_reason = Column(String(50), nullable=False)
    trade_id = Column(UUID(as_uuid=True), ForeignKey("trades.id"))
    alpha_used = Column(Numeric(4, 3))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class CalibrationRun(Base):
    __tablename__ = "calibration_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cadence = Column(String(20), nullable=False)
    profile = Column(String(50))
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="running")
    threshold_changes = Column(JSONB)
    precision_scores = Column(JSONB)
    recall_scores = Column(JSONB)
    f1_scores = Column(JSONB)
    sharpe_rolling = Column(Numeric(6, 3))
    similar_regimes_found = Column(JSONB)
    weights_blended = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════
# MARKET DATA & REGIMES
# ═══════════════════════════════════════

class MarketRegime(Base):
    __tablename__ = "market_regimes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    regime = Column(String(50), nullable=False)
    confidence = Column(Numeric(4, 3), nullable=False)
    previous_regime = Column(String(50))
    transition_reason = Column(String(500))
    feature_vector = Column(ARRAY(Numeric))
    detector_version = Column(String(20), nullable=False, default="v1")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    regime_id = Column(String(100), unique=True, nullable=False)
    regime_type = Column(String(50), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True))
    feature_vector = Column(ARRAY(Numeric), nullable=False)
    agent_performance = Column(JSONB, nullable=False)
    optimal_weights = Column(JSONB, nullable=False)
    optimal_thresholds = Column(JSONB, nullable=False)
    total_trades = Column(Integer, nullable=False)
    win_rate = Column(Numeric(5, 4))
    avg_pnl_pct = Column(Numeric(8, 4))
    sharpe_ratio = Column(Numeric(6, 3))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════
# EVENTS & LOGS
# ═══════════════════════════════════════

class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    event_time = Column(DateTime(timezone=True), nullable=False)
    name = Column(String(300), nullable=False)
    country = Column(String(5), nullable=False)
    impact = Column(String(10), nullable=False)
    category = Column(String(50))
    forecast = Column(Numeric(12, 4))
    previous = Column(Numeric(12, 4))
    actual = Column(Numeric(12, 4))
    surprise = Column(Numeric(12, 4))
    affected_assets = Column(ARRAY(Text))
    source = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    event_type = Column(String(50), nullable=False)
    severity = Column(String(10), nullable=False)
    details = Column(JSONB, nullable=False)
    auto_response = Column(String(100))
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(UUID(as_uuid=True))
    details = Column(JSONB)
    ip_address = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    broker_name = Column(String(50), nullable=False)
    account_id = Column(String(100), nullable=False)
    credentials_encrypted = Column(BYTEA, nullable=False)
    is_live = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    last_health_check = Column(DateTime(timezone=True))
    last_health_status = Column(String(20))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
