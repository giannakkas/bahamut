"""
Paper Trading API Router — Frontend endpoints for demo trading dashboard.
"""

import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from bahamut.database import get_db
from bahamut.paper_trading.models import (
    PaperPortfolio, PaperPosition, AgentTradePerformance,
    LearningEvent, PositionStatus,
)
from bahamut.paper_trading.engine import get_portfolio_summary
from bahamut.paper_trading.learning import get_agent_leaderboard

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/paper-trading", tags=["Paper Trading"])


@router.get("/portfolio")
async def get_portfolio():
    """Get current portfolio summary with open positions."""
    try:
        return await get_portfolio_summary()
    except Exception as e:
        logger.error("portfolio_fetch_failed", error=str(e))
        raise HTTPException(500, f"Failed to fetch portfolio: {str(e)}")


@router.get("/positions")
async def get_positions(
    status: str = Query(None, description="Filter: OPEN, CLOSED_TP, CLOSED_SL, etc."),
    asset: str = Query(None, description="Filter by asset"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """Get trade history with filters."""
    query = select(PaperPosition).order_by(desc(PaperPosition.opened_at))

    if status:
        query = query.where(PaperPosition.status == status)
    if asset:
        query = query.where(PaperPosition.asset == asset)

    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    positions = result.scalars().all()

    return {
        "positions": [
            {
                "id": p.id,
                "asset": p.asset,
                "direction": p.direction,
                "entry_price": p.entry_price,
                "exit_price": p.exit_price,
                "current_price": p.current_price,
                "quantity": p.quantity,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "realized_pnl": p.realized_pnl,
                "realized_pnl_pct": p.realized_pnl_pct,
                "status": p.status,
                "signal_score": p.entry_signal_score,
                "signal_label": p.entry_signal_label,
                "agent_votes": p.agent_votes,
                "consensus_score": p.consensus_score,
                "max_favorable": p.max_favorable,
                "max_adverse": p.max_adverse,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                "learning_processed": p.learning_processed,
            }
            for p in positions
        ],
        "total": len(positions),
    }


@router.get("/leaderboard")
async def get_leaderboard():
    """
    Agent leaderboard — who's the smartest?
    Ranked by accuracy across all assets.
    """
    try:
        return {"agents": await get_agent_leaderboard()}
    except Exception as e:
        logger.error("leaderboard_fetch_failed", error=str(e))
        raise HTTPException(500, str(e))


@router.get("/agent-performance/{agent_name}")
async def get_agent_detail(
    agent_name: str,
    session: AsyncSession = Depends(get_db),
):
    """Detailed performance for a specific agent across all assets."""
    result = await session.execute(
        select(AgentTradePerformance).where(
            AgentTradePerformance.agent_name == agent_name
        )
    )
    records = result.scalars().all()

    if not records:
        return {"agent": agent_name, "message": "No trade data yet", "assets": []}

    total_correct = sum(r.correct_signals for r in records)
    total_wrong = sum(r.wrong_signals for r in records)
    total_directional = total_correct + total_wrong

    return {
        "agent": agent_name,
        "overall_accuracy": round(total_correct / total_directional, 3) if total_directional > 0 else 0,
        "total_trades": sum(r.total_signals for r in records),
        "assets": [
            {
                "asset": r.asset,
                "accuracy": round(r.accuracy, 3),
                "total_signals": r.total_signals,
                "correct": r.correct_signals,
                "wrong": r.wrong_signals,
                "neutral": r.neutral_signals,
                "profit_factor": round(r.profit_factor, 2),
                "avg_confidence_correct": round(r.avg_confidence_when_correct, 3),
                "avg_confidence_wrong": round(r.avg_confidence_when_wrong, 3),
                "current_streak": r.current_streak,
                "best_streak": r.best_streak,
                "worst_streak": r.worst_streak,
            }
            for r in records
        ],
    }


@router.get("/learning-log")
async def get_learning_log(
    agent_name: str = Query(None),
    asset: str = Query(None),
    limit: int = Query(30, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    """Audit trail of every trust score adjustment."""
    query = select(LearningEvent).order_by(desc(LearningEvent.created_at))

    if agent_name:
        query = query.where(LearningEvent.agent_name == agent_name)
    if asset:
        query = query.where(LearningEvent.asset == asset)

    query = query.limit(limit)
    result = await session.execute(query)
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": e.id,
                "position_id": e.position_id,
                "agent": e.agent_name,
                "asset": e.asset,
                "agent_direction": e.agent_direction,
                "actual_outcome": e.actual_outcome,
                "confidence": e.agent_confidence,
                "was_correct": e.was_correct,
                "trust_delta": e.trust_delta,
                "pnl": e.position_pnl,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.post("/reset")
async def reset_portfolio(session: AsyncSession = Depends(get_db)):
    """Reset paper portfolio to starting state. USE WITH CAUTION."""
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.name == "SYSTEM_DEMO")
    )
    portfolio = result.scalar_one_or_none()

    if portfolio:
        portfolio.current_balance = portfolio.initial_balance
        portfolio.total_pnl = 0.0
        portfolio.total_pnl_pct = 0.0
        portfolio.total_trades = 0
        portfolio.winning_trades = 0
        portfolio.losing_trades = 0
        portfolio.win_rate = 0.0
        portfolio.best_trade_pnl = 0.0
        portfolio.worst_trade_pnl = 0.0
        portfolio.max_drawdown = 0.0
        portfolio.peak_balance = portfolio.initial_balance
        portfolio.is_active = True
        portfolio.updated_at = datetime.now(timezone.utc)
        await session.commit()

    logger.warning("paper_portfolio_reset")
    return {"status": "reset", "balance": portfolio.initial_balance if portfolio else 100_000.0}


@router.post("/toggle")
async def toggle_paper_trading(
    active: bool = Query(..., description="Enable or disable paper trading"),
    session: AsyncSession = Depends(get_db),
):
    """Enable/disable automatic paper trading."""
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.name == "SYSTEM_DEMO")
    )
    portfolio = result.scalar_one_or_none()

    if portfolio:
        portfolio.is_active = active
        await session.commit()

    return {"active": active}


@router.get("/stats")
async def get_performance_stats(session: AsyncSession = Depends(get_db)):
    """Aggregated stats for the performance dashboard."""
    # Get portfolio
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.name == "SYSTEM_DEMO")
    )
    portfolio = result.scalar_one_or_none()

    # Get recent trades
    result = await session.execute(
        select(PaperPosition)
        .where(PaperPosition.status != PositionStatus.OPEN.value)
        .order_by(desc(PaperPosition.closed_at))
        .limit(100)
    )
    closed_trades = result.scalars().all()

    # Calculate stats
    wins = [t for t in closed_trades if t.realized_pnl and t.realized_pnl > 0]
    losses = [t for t in closed_trades if t.realized_pnl and t.realized_pnl < 0]
    avg_win = sum(t.realized_pnl for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.realized_pnl for t in losses) / len(losses) if losses else 0

    # Per-asset breakdown
    asset_stats = {}
    for t in closed_trades:
        if t.asset not in asset_stats:
            asset_stats[t.asset] = {"wins": 0, "losses": 0, "pnl": 0}
        if t.realized_pnl and t.realized_pnl > 0:
            asset_stats[t.asset]["wins"] += 1
        elif t.realized_pnl and t.realized_pnl < 0:
            asset_stats[t.asset]["losses"] += 1
        asset_stats[t.asset]["pnl"] += t.realized_pnl or 0

    # Per-signal-label breakdown
    label_stats = {}
    for t in closed_trades:
        label = t.entry_signal_label or "UNKNOWN"
        if label not in label_stats:
            label_stats[label] = {"trades": 0, "wins": 0, "total_pnl": 0}
        label_stats[label]["trades"] += 1
        if t.realized_pnl and t.realized_pnl > 0:
            label_stats[label]["wins"] += 1
        label_stats[label]["total_pnl"] += t.realized_pnl or 0

    return {
        "portfolio": {
            "balance": round(portfolio.current_balance, 2) if portfolio else 100_000,
            "total_pnl": round(portfolio.total_pnl, 2) if portfolio else 0,
            "total_pnl_pct": round(portfolio.total_pnl_pct, 2) if portfolio else 0,
            "win_rate": round(portfolio.win_rate, 1) if portfolio else 0,
            "total_trades": portfolio.total_trades if portfolio else 0,
            "max_drawdown": portfolio.max_drawdown if portfolio else 0,
        },
        "averages": {
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(avg_win + avg_loss, 2),  # Simplified expectancy
        },
        "by_asset": {
            asset: {
                "win_rate": round(s["wins"] / (s["wins"] + s["losses"]) * 100, 1) if (s["wins"] + s["losses"]) > 0 else 0,
                "total_pnl": round(s["pnl"], 2),
                "trades": s["wins"] + s["losses"],
            }
            for asset, s in asset_stats.items()
        },
        "by_signal_type": label_stats,
    }
