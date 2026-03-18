"""
Learning Feedback Loop — The brain of self-education.

When a trade closes:
1. Look at each agent's vote (direction + confidence)
2. Compare to actual outcome (profitable or not)
3. Reward agents that were right, penalize agents that were wrong
4. Update per-agent, per-asset accuracy stats
5. Push updated trust scores back into consensus engine

This is what makes Bahamut.AI get smarter every day.
"""

import structlog
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bahamut.database import AsyncSessionLocal
from bahamut.paper_trading.models import (
    PaperPosition, AgentTradePerformance, LearningEvent, PositionStatus
)

logger = structlog.get_logger(__name__)

# --- Learning Parameters ---
# These control HOW FAST the system learns

# Trust score adjustments (applied to consensus/trust_store.py)
TRUST_REWARD_CORRECT = 0.015      # Boost trust when agent was right
TRUST_PENALTY_WRONG = 0.025       # Penalize more harshly when wrong (asymmetric!)
TRUST_BONUS_HIGH_CONFIDENCE = 0.01  # Extra bonus when correct AND high confidence (>0.7)
TRUST_PENALTY_HIGH_CONFIDENCE = 0.015  # Extra penalty when wrong AND high confidence

TRUST_MIN = 0.3                   # Floor — never trust an agent less than this
TRUST_MAX = 1.5                   # Ceiling — never trust more than this

# Confidence threshold for "high confidence" bonus/penalty
HIGH_CONFIDENCE_THRESHOLD = 0.7

# Minimum trades before agent performance significantly affects trust
MIN_TRADES_FOR_WEIGHT = 10

# Agent names expected in votes
AGENT_NAMES = ["technical", "macro", "sentiment", "volatility", "liquidity", "risk"]


async def process_closed_trade(closed_trade: dict) -> dict:
    """
    Process a single closed trade through the learning loop.

    closed_trade format (from engine.close_position):
    {
        "position_id": 1,
        "asset": "EURUSD",
        "direction": "LONG",
        "entry_price": 1.0850,
        "exit_price": 1.0900,
        "pnl": 500.0,
        "pnl_pct": 2.5,
        "status": "CLOSED_TP",
        "agent_votes": {"technical": {"direction": "LONG", "confidence": 0.78}, ...},
        "consensus_score": 0.65,
    }
    """
    position_id = closed_trade["position_id"]
    asset = closed_trade["asset"]
    trade_direction = closed_trade["direction"]
    pnl = closed_trade["pnl"]
    agent_votes = closed_trade.get("agent_votes", {})
    cycle_id = closed_trade.get("cycle_id")

    is_profitable = pnl > 0
    actual_outcome = trade_direction if is_profitable else (
        "SHORT" if trade_direction == "LONG" else "LONG"
    )

    log = logger.bind(position_id=position_id, asset=asset, pnl=pnl)
    log.info("learning_processing_trade", profitable=is_profitable)

    # ── Resolve context for dimensional trust updates ──
    asset_class = _infer_asset_class(asset)
    trade_context = {"regime": "risk_on", "asset_class": asset_class, "timeframe": "4H"}

    if cycle_id:
        # Try to pull regime + timeframe from the decision trace
        try:
            from bahamut.database import sync_engine as _sync_eng
            from sqlalchemy import text as _text
            with _sync_eng.connect() as _conn:
                _tr = _conn.execute(_text(
                    "SELECT regime, timeframe FROM decision_traces WHERE cycle_id = :c LIMIT 1"
                ), {"c": cycle_id}).mappings().first()
                if _tr:
                    trade_context["regime"] = _tr.get("regime") or "risk_on"
                    trade_context["timeframe"] = _tr.get("timeframe") or "4H"
        except Exception as e:
            log.debug("trace_lookup_skipped", error=str(e))

        # Close the decision trace with outcome
        try:
            from bahamut.agents.persistence import close_decision_trace
            close_decision_trace(cycle_id, {
                "pnl": pnl, "pnl_pct": closed_trade.get("pnl_pct", 0),
                "status": closed_trade.get("status", ""),
                "exit_price": closed_trade.get("exit_price", 0),
                "profitable": is_profitable,
            })
        except Exception as e:
            log.debug("close_trace_skipped", error=str(e))

    adjustments = {}

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Mark position as processed
            result = await session.execute(
                select(PaperPosition).where(PaperPosition.id == position_id)
            )
            position = result.scalar_one_or_none()
            if not position:
                log.error("learning_position_not_found")
                return {"error": "Position not found"}
            if position.learning_processed:
                log.info("learning_already_processed")
                return {"status": "already_processed"}

            position.learning_processed = True

            # Process each agent's vote
            for agent_name in AGENT_NAMES:
                vote = agent_votes.get(agent_name)
                if not vote:
                    continue

                agent_direction = vote.get("direction", "NEUTRAL")
                agent_confidence = vote.get("confidence", 0.5)

                # Determine if agent was correct
                if agent_direction == "NEUTRAL":
                    was_correct = None  # Neutral = abstained
                elif is_profitable:
                    was_correct = (agent_direction == trade_direction)
                else:
                    was_correct = (agent_direction != trade_direction)

                # Calculate trust adjustment
                trust_delta = _calculate_trust_delta(
                    was_correct, agent_confidence, pnl
                )

                # Get/create agent performance record
                perf = await _get_or_create_performance(
                    session, agent_name, asset
                )

                # Update performance stats
                perf.total_signals += 1
                if was_correct is None:
                    perf.neutral_signals += 1
                elif was_correct:
                    perf.correct_signals += 1
                    perf.total_pnl_when_agreed += abs(pnl)
                    # Update confidence tracking
                    n = perf.correct_signals
                    perf.avg_confidence_when_correct = (
                        (perf.avg_confidence_when_correct * (n - 1) + agent_confidence) / n
                    )
                    # Streak
                    if perf.current_streak >= 0:
                        perf.current_streak += 1
                    else:
                        perf.current_streak = 1
                    perf.best_streak = max(perf.best_streak, perf.current_streak)
                else:
                    perf.wrong_signals += 1
                    perf.total_pnl_when_disagreed += abs(pnl)
                    n = perf.wrong_signals
                    perf.avg_confidence_when_wrong = (
                        (perf.avg_confidence_when_wrong * (n - 1) + agent_confidence) / n
                    )
                    if perf.current_streak <= 0:
                        perf.current_streak -= 1
                    else:
                        perf.current_streak = -1
                    perf.worst_streak = min(perf.worst_streak, perf.current_streak)

                # Update accuracy
                total_directional = perf.correct_signals + perf.wrong_signals
                if total_directional > 0:
                    perf.accuracy = perf.correct_signals / total_directional

                # Update profit factor
                if perf.total_pnl_when_disagreed > 0:
                    perf.profit_factor = (
                        perf.total_pnl_when_agreed / perf.total_pnl_when_disagreed
                    )

                perf.last_updated = datetime.now(timezone.utc)

                # Create audit log
                agent_id_full = f"{agent_name}_agent"
                from bahamut.consensus.trust_store import trust_store as _ts
                _tb, _ = _ts.get(agent_id_full, "global")

                learning_event = LearningEvent(
                    position_id=position_id,
                    agent_name=agent_name,
                    asset=asset,
                    agent_direction=agent_direction,
                    actual_outcome=actual_outcome,
                    agent_confidence=agent_confidence,
                    was_correct=was_correct,
                    trust_before=round(_tb, 4),
                    trust_after=0,   # filled after apply_trust_adjustments
                    trust_delta=trust_delta,
                    position_pnl=pnl,
                    position_pnl_pct=closed_trade.get("pnl_pct", 0),
                )
                session.add(learning_event)

                adjustments[agent_name] = {
                    "direction": agent_direction,
                    "confidence": agent_confidence,
                    "was_correct": was_correct,
                    "trust_delta": trust_delta,
                    "accuracy": round(perf.accuracy, 3),
                    "total_trades": perf.total_signals,
                    "streak": perf.current_streak,
                }

                log.info("learning_agent_processed",
                         agent=agent_name,
                         correct=was_correct,
                         delta=trust_delta,
                         accuracy=round(perf.accuracy, 3))

    return {
        "position_id": position_id,
        "asset": asset,
        "pnl": pnl,
        "profitable": is_profitable,
        "adjustments": adjustments,
        "context": trade_context,
        "cycle_id": cycle_id,
    }


def _calculate_trust_delta(
    was_correct: bool | None,
    confidence: float,
    pnl: float,
) -> float:
    """
    Calculate trust score adjustment for an agent.

    Key principles:
    - Asymmetric: wrong costs more than right rewards (forces agents to be careful)
    - High-confidence amplifier: confident and right = extra bonus, confident and wrong = extra pain
    - Neutral agents get no adjustment (but also no reward)
    """
    if was_correct is None:
        return 0.0

    if was_correct:
        delta = TRUST_REWARD_CORRECT
        if confidence >= HIGH_CONFIDENCE_THRESHOLD:
            delta += TRUST_BONUS_HIGH_CONFIDENCE
    else:
        delta = -TRUST_PENALTY_WRONG
        if confidence >= HIGH_CONFIDENCE_THRESHOLD:
            delta -= TRUST_PENALTY_HIGH_CONFIDENCE

    # Scale slightly by confidence (higher confidence = larger magnitude)
    delta *= (0.7 + 0.6 * confidence)

    return round(delta, 4)


async def apply_trust_adjustments(
    adjustments: dict[str, dict],
    regime: str = "risk_on",
    asset_class: str = "fx",
    timeframe: str = "4H",
    trade_id: str = None,
) -> dict:
    """
    Push trust deltas into the consensus trust store.
    Uses real trade context for multi-dimensional updates.
    """
    from bahamut.consensus.trust_store import trust_store

    results = {}
    for agent_name, adj in adjustments.items():
        was_correct = adj.get("was_correct")
        if was_correct is None:
            continue

        confidence = adj.get("confidence", 0.5)
        agent_id = f"{agent_name}_agent"

        try:
            # Get score before update
            before, _ = trust_store.get(agent_id, "global")

            # Use real context for multi-dimensional update
            trust_store.update_after_trade(
                agent_id=agent_id,
                outcome_correct=was_correct,
                confidence=confidence,
                regime=regime,
                asset_class=asset_class,
                timeframe=timeframe,
                trade_id=trade_id,
            )

            after, _ = trust_store.get(agent_id, "global")
            results[agent_name] = {
                "before": round(before, 4),
                "after": round(after, 4),
                "delta": round(after - before, 4),
            }
            logger.info("trust_score_updated",
                        agent=agent_name,
                        before=round(before, 4),
                        after=round(after, 4),
                        regime=regime, asset_class=asset_class)
        except Exception as e:
            logger.error("trust_update_failed", agent=agent_name, error=str(e))
            results[agent_name] = {"error": str(e)}

    return results


async def get_agent_leaderboard() -> list[dict]:
    """Get all agents ranked by accuracy across all assets."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentTradePerformance).order_by(
                AgentTradePerformance.accuracy.desc()
            )
        )
        records = result.scalars().all()

        # Aggregate per agent
        agents = {}
        for r in records:
            if r.agent_name not in agents:
                agents[r.agent_name] = {
                    "agent": r.agent_name,
                    "total_signals": 0,
                    "correct": 0,
                    "wrong": 0,
                    "neutral": 0,
                    "accuracy": 0,
                    "best_streak": 0,
                    "worst_streak": 0,
                    "assets": {},
                }
            a = agents[r.agent_name]
            a["total_signals"] += r.total_signals
            a["correct"] += r.correct_signals
            a["wrong"] += r.wrong_signals
            a["neutral"] += r.neutral_signals
            a["best_streak"] = max(a["best_streak"], r.best_streak)
            a["worst_streak"] = min(a["worst_streak"], r.worst_streak)
            a["assets"][r.asset] = {
                "accuracy": round(r.accuracy, 3),
                "trades": r.total_signals,
                "streak": r.current_streak,
            }

        # Calculate overall accuracy
        for a in agents.values():
            total = a["correct"] + a["wrong"]
            a["accuracy"] = round(a["correct"] / total, 3) if total > 0 else 0

        return sorted(agents.values(), key=lambda x: x["accuracy"], reverse=True)


async def _get_or_create_performance(
    session: AsyncSession, agent_name: str, asset: str
) -> AgentTradePerformance:
    """Get or create an agent performance record."""
    result = await session.execute(
        select(AgentTradePerformance).where(
            and_(
                AgentTradePerformance.agent_name == agent_name,
                AgentTradePerformance.asset == asset,
            )
        )
    )
    perf = result.scalar_one_or_none()

    if not perf:
        perf = AgentTradePerformance(agent_name=agent_name, asset=asset)
        session.add(perf)
        await session.flush()

    return perf


_CRYPTO = {"BTCUSD","ETHUSD","SOLUSD","BNBUSD","XRPUSD","ADAUSD","DOGEUSD",
           "AVAXUSD","DOTUSD","LINKUSD","MATICUSD","SHIBUSD"}
_COMMODITY = {"XAUUSD","XAGUSD","WTIUSD","BCOUSD"}
_STOCKS = {"AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","UNH",
           "MA","HD","PG","JNJ","AMD","CRM","NFLX","ADBE","INTC","PYPL","UBER",
           "SQ","SHOP","SNOW","PLTR","COIN","RBLX","MARA","RIOT"}

def _infer_asset_class(asset: str) -> str:
    """Infer asset class from symbol for dimensional trust updates."""
    if asset in _CRYPTO: return "crypto"
    if asset in _COMMODITY: return "commodities"
    if asset in _STOCKS: return "indices"
    if len(asset) == 6 and asset.endswith("USD"): return "fx"
    if len(asset) == 6 and "EUR" in asset or "GBP" in asset or "JPY" in asset: return "fx"
    return "fx"
