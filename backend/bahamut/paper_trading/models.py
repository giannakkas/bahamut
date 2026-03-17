"""
Paper Trading Models — Self-Learning Demo Trading System
Tracks demo portfolio, positions, and per-agent performance for trust score updates.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, JSON, Text,
    Enum as SAEnum, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from bahamut.database import Base
import enum


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"       # Hit take profit
    CLOSED_SL = "CLOSED_SL"       # Hit stop loss
    CLOSED_MANUAL = "CLOSED_MANUAL"
    CLOSED_TIMEOUT = "CLOSED_TIMEOUT"  # Max hold time exceeded
    CLOSED_SIGNAL = "CLOSED_SIGNAL"    # Opposite signal fired


class TradeDirection(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PaperPortfolio(Base):
    """Demo trading portfolio — one system-wide portfolio for self-learning."""
    __tablename__ = "paper_portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), default="SYSTEM_DEMO", nullable=False)
    initial_balance = Column(Float, default=100_000.0, nullable=False)
    current_balance = Column(Float, default=100_000.0, nullable=False)
    total_pnl = Column(Float, default=0.0)
    total_pnl_pct = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    best_trade_pnl = Column(Float, default=0.0)
    worst_trade_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    peak_balance = Column(Float, default=100_000.0)
    is_active = Column(Boolean, default=True)
    risk_per_trade_pct = Column(Float, default=2.0)    # % of portfolio per trade
    max_open_positions = Column(Integer, default=5)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    positions = relationship("PaperPosition", back_populates="portfolio", lazy="selectin")


class PaperPosition(Base):
    """Individual paper trade with full agent attribution for learning."""
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("paper_portfolios.id"), nullable=False)
    asset = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # LONG or SHORT

    # Entry
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)          # Position size in units
    position_value = Column(Float, nullable=False)    # $ value at entry
    entry_signal_score = Column(Float, nullable=False)
    entry_signal_label = Column(String(30))           # STRONG_SIGNAL, SIGNAL, WEAK_SIGNAL

    # Risk management
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    risk_amount = Column(Float, nullable=False)       # $ at risk
    atr_at_entry = Column(Float)                      # ATR used for SL/TP calc

    # Current state
    current_price = Column(Float)
    unrealized_pnl = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)

    # Close
    exit_price = Column(Float)
    realized_pnl = Column(Float)
    realized_pnl_pct = Column(Float)
    status = Column(String(20), default=PositionStatus.OPEN.value)

    # Agent attribution — WHO voted for this trade and how confident
    # Format: {"technical": {"direction": "LONG", "confidence": 0.78, "score": 0.65}, ...}
    agent_votes = Column(JSON, nullable=False)
    consensus_score = Column(Float, nullable=False)

    # Cycle reference
    cycle_id = Column(String(100))

    # Timestamps
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime)
    max_favorable = Column(Float, default=0.0)    # Best unrealized PnL during trade
    max_adverse = Column(Float, default=0.0)      # Worst unrealized PnL during trade

    # Learning flag — has this trade been processed by the learning loop?
    learning_processed = Column(Boolean, default=False)

    portfolio = relationship("PaperPortfolio", back_populates="positions")

    __table_args__ = (
        Index("ix_paper_positions_status", "status"),
        Index("ix_paper_positions_asset", "asset"),
        Index("ix_paper_positions_opened_at", "opened_at"),
    )


class AgentTradePerformance(Base):
    """
    Per-agent, per-asset accuracy tracking.
    This is the brain — it feeds back into trust_store.py weights.
    """
    __tablename__ = "agent_trade_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(50), nullable=False)   # technical, macro, sentiment, etc.
    asset = Column(String(20), nullable=False)

    total_signals = Column(Integer, default=0)
    correct_signals = Column(Integer, default=0)
    wrong_signals = Column(Integer, default=0)
    neutral_signals = Column(Integer, default=0)      # Agent said NEUTRAL

    accuracy = Column(Float, default=0.0)             # correct / (correct + wrong)
    profit_factor = Column(Float, default=0.0)        # sum(wins) / sum(losses)

    avg_confidence_when_correct = Column(Float, default=0.0)
    avg_confidence_when_wrong = Column(Float, default=0.0)

    # Running totals for profit factor calc
    total_pnl_when_agreed = Column(Float, default=0.0)
    total_pnl_when_disagreed = Column(Float, default=0.0)

    # Streak tracking
    current_streak = Column(Integer, default=0)       # + for wins, - for losses
    best_streak = Column(Integer, default=0)
    worst_streak = Column(Integer, default=0)

    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_agent_perf_name_asset", "agent_name", "asset", unique=True),
    )


class LearningEvent(Base):
    """Audit log of every trust score adjustment — full traceability."""
    __tablename__ = "learning_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("paper_positions.id"), nullable=False)
    agent_name = Column(String(50), nullable=False)
    asset = Column(String(20), nullable=False)

    agent_direction = Column(String(10))     # What agent predicted
    actual_outcome = Column(String(10))      # What actually happened
    agent_confidence = Column(Float)
    was_correct = Column(Boolean)

    trust_before = Column(Float)
    trust_after = Column(Float)
    trust_delta = Column(Float)

    position_pnl = Column(Float)
    position_pnl_pct = Column(Float)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_learning_events_agent", "agent_name"),
        Index("ix_learning_events_created", "created_at"),
    )
