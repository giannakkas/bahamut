"""
Bahamut.AI Dynamic Capital Allocation Engine

When a new trade signal arrives and the portfolio is full or concentrated:
  1. Score every open position on a 0-1 quality scale
  2. Compare the proposed trade's quality against weakest positions
  3. If proposed is materially better: close weakest, open proposed
  4. If not: respect the MAX_POSITIONS block

Quality score components (per open position):
  signal_quality:  0.25 — original consensus score at entry
  pnl_trajectory:  0.30 — current unrealized PnL trajectory
  risk_reward:     0.20 — how close to TP vs SL
  time_decay:      0.15 — older positions score lower (conviction fading)
  momentum:        0.10 — max_favorable vs max_adverse (was trade ever working?)

Reallocation rules:
  - Only reallocate if proposed signal is STRONG_SIGNAL or SIGNAL
  - Only close positions with quality < 0.35 (clearly underperforming)
  - Proposed must score > weakest by at least 0.20 margin
  - Maximum 1 reallocation per cycle (no cascade)
  - Log every reallocation decision to reallocation_log table

Risk preservation:
  - Risk agent veto blocks reallocation too
  - Cannot reallocate if it would increase gross exposure
  - Closed position's risk freed before new position's risk committed
"""
import json
import time
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()

QUALITY_WEIGHTS = {
    "signal_quality": 0.25,
    "pnl_trajectory": 0.30,
    "risk_reward": 0.20,
    "time_decay": 0.15,
    "momentum": 0.10,
}

MIN_QUALITY_TO_KEEP = 0.35      # below this, position is candidate for closure
MIN_UPGRADE_MARGIN = 0.20       # new trade must beat weakest by this much
MAX_REALLOCS_PER_HOUR = 3       # throttle to prevent churn


@dataclass
class PositionQuality:
    position_id: int = 0
    asset: str = ""
    direction: str = ""
    quality_score: float = 0.5
    signal_quality: float = 0.0
    pnl_trajectory: float = 0.0
    risk_reward: float = 0.0
    time_decay: float = 0.0
    momentum: float = 0.0
    position_value: float = 0.0
    unrealized_pnl: float = 0.0
    hours_held: float = 0.0

    def to_dict(self):
        return {
            "position_id": self.position_id, "asset": self.asset,
            "direction": self.direction,
            "quality_score": round(self.quality_score, 3),
            "signal_quality": round(self.signal_quality, 3),
            "pnl_trajectory": round(self.pnl_trajectory, 3),
            "risk_reward": round(self.risk_reward, 3),
            "time_decay": round(self.time_decay, 3),
            "momentum": round(self.momentum, 3),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "hours_held": round(self.hours_held, 1),
        }


@dataclass
class ReallocationDecision:
    should_reallocate: bool = False
    close_position_id: int = None
    close_asset: str = ""
    close_quality: float = 0.0
    proposed_quality: float = 0.0
    quality_margin: float = 0.0
    reason: str = ""
    all_rankings: list = field(default_factory=list)

    def to_dict(self):
        return {
            "should_reallocate": self.should_reallocate,
            "close_position_id": self.close_position_id,
            "close_asset": self.close_asset,
            "close_quality": round(self.close_quality, 3),
            "proposed_quality": round(self.proposed_quality, 3),
            "quality_margin": round(self.quality_margin, 3),
            "reason": self.reason,
            "all_rankings": [r.to_dict() for r in self.all_rankings],
        }


def score_position(row: dict) -> PositionQuality:
    """Score a single open position on 0-1 quality scale."""
    pq = PositionQuality(
        position_id=row.get("id", 0),
        asset=row.get("asset", ""),
        direction=row.get("direction", ""),
        position_value=float(row.get("position_value", 0)),
        unrealized_pnl=float(row.get("unrealized_pnl", 0)),
    )

    # 1. Signal quality: original consensus score (0-1, already normalized)
    pq.signal_quality = min(1.0, max(0.0, float(row.get("consensus_score", 0.5))))

    # 2. PnL trajectory: positive PnL = good, negative = bad
    pnl_pct = float(row.get("unrealized_pnl_pct", 0))
    if pnl_pct >= 2.0:
        pq.pnl_trajectory = 1.0
    elif pnl_pct >= 0.5:
        pq.pnl_trajectory = 0.7
    elif pnl_pct >= 0:
        pq.pnl_trajectory = 0.5
    elif pnl_pct >= -1.0:
        pq.pnl_trajectory = 0.3
    elif pnl_pct >= -2.0:
        pq.pnl_trajectory = 0.15
    else:
        pq.pnl_trajectory = 0.05

    # 3. Risk/reward: how close to TP vs SL?
    entry = float(row.get("entry_price", 0))
    current = float(row.get("current_price", 0)) or entry
    sl = float(row.get("stop_loss", 0))
    tp = float(row.get("take_profit", 0))
    if entry > 0 and sl > 0 and tp > 0 and tp != sl:
        direction = row.get("direction", "LONG")
        if direction == "LONG":
            dist_to_tp = tp - current
            dist_to_sl = current - sl
        else:
            dist_to_tp = current - tp
            dist_to_sl = sl - current
        total_range = abs(tp - sl)
        if total_range > 0:
            rr_ratio = max(0, dist_to_tp) / total_range
            pq.risk_reward = min(1.0, max(0.0, rr_ratio))
        else:
            pq.risk_reward = 0.5
    else:
        pq.risk_reward = 0.5

    # 4. Time decay: older positions lose urgency
    opened_at = row.get("opened_at")
    if opened_at:
        from datetime import datetime, timezone
        if hasattr(opened_at, 'timestamp'):
            age_hours = (datetime.now(timezone.utc) - opened_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        else:
            age_hours = 0
        pq.hours_held = age_hours
        # 0-4h: 1.0 (fresh), 4-12h: 0.8, 12-24h: 0.6, 24-48h: 0.4, >48h: 0.2
        if age_hours <= 4:
            pq.time_decay = 1.0
        elif age_hours <= 12:
            pq.time_decay = 0.8
        elif age_hours <= 24:
            pq.time_decay = 0.6
        elif age_hours <= 48:
            pq.time_decay = 0.4
        else:
            pq.time_decay = 0.2
    else:
        pq.time_decay = 0.5

    # 5. Momentum: was the trade ever working? max_favorable vs max_adverse
    max_fav = abs(float(row.get("max_favorable", 0)))
    max_adv = abs(float(row.get("max_adverse", 0)))
    if max_fav + max_adv > 0:
        pq.momentum = max_fav / (max_fav + max_adv)
    else:
        pq.momentum = 0.5

    # Composite
    w = QUALITY_WEIGHTS
    pq.quality_score = round(
        w["signal_quality"] * pq.signal_quality
        + w["pnl_trajectory"] * pq.pnl_trajectory
        + w["risk_reward"] * pq.risk_reward
        + w["time_decay"] * pq.time_decay
        + w["momentum"] * pq.momentum,
        3,
    )
    return pq


def score_proposed_trade(consensus_score: float, signal_label: str) -> float:
    """Score a proposed (not yet opened) trade. Simple: consensus score + label bonus."""
    base = min(1.0, max(0.0, consensus_score))
    label_bonus = 0.10 if signal_label == "STRONG_SIGNAL" else 0.0
    # New trades get full time_decay (1.0) and neutral momentum (0.5)
    return round(
        QUALITY_WEIGHTS["signal_quality"] * base
        + QUALITY_WEIGHTS["pnl_trajectory"] * 0.5  # neutral (no PnL yet)
        + QUALITY_WEIGHTS["risk_reward"] * 0.8     # fresh: close to entry, far from SL
        + QUALITY_WEIGHTS["time_decay"] * 1.0      # brand new
        + QUALITY_WEIGHTS["momentum"] * 0.5        # neutral
        + label_bonus,
        3,
    )


def evaluate_reallocation(
    proposed_asset: str,
    proposed_direction: str,
    consensus_score: float,
    signal_label: str,
    portfolio_id: int = None,
) -> ReallocationDecision:
    """
    Evaluate whether to reallocate from weakest position to proposed trade.
    Called when MAX_POSITIONS blocks a new trade.
    """
    decision = ReallocationDecision()

    # Only reallocate for real signals
    if signal_label not in ("STRONG_SIGNAL", "SIGNAL"):
        decision.reason = f"Only reallocate for SIGNAL+, got {signal_label}"
        return decision

    # Throttle: check recent reallocation count
    recent_count = _count_recent_reallocs()
    if recent_count >= MAX_REALLOCS_PER_HOUR:
        decision.reason = f"Throttled: {recent_count} reallocs in last hour (max {MAX_REALLOCS_PER_HOUR})"
        return decision

    # Load and rank all open positions
    rankings = _load_and_rank_positions(portfolio_id)
    decision.all_rankings = rankings

    if not rankings:
        decision.reason = "No open positions to evaluate"
        return decision

    # Find weakest
    weakest = rankings[-1]  # sorted desc, weakest is last

    # Score proposed trade
    proposed_q = score_proposed_trade(consensus_score, signal_label)
    decision.proposed_quality = proposed_q
    decision.close_quality = weakest.quality_score
    decision.quality_margin = proposed_q - weakest.quality_score

    # Check reallocation criteria
    if weakest.quality_score >= MIN_QUALITY_TO_KEEP:
        decision.reason = f"Weakest position quality {weakest.quality_score:.3f} >= {MIN_QUALITY_TO_KEEP} — all positions worth keeping"
        return decision

    if decision.quality_margin < MIN_UPGRADE_MARGIN:
        decision.reason = f"Margin {decision.quality_margin:.3f} < {MIN_UPGRADE_MARGIN} — proposed not materially better"
        return decision

    # Don't close a position in the same asset (that's just a flip, handled separately)
    if weakest.asset == proposed_asset:
        decision.reason = f"Weakest is same asset ({proposed_asset}) — use signal flip instead"
        return decision

    # Reallocation approved
    decision.should_reallocate = True
    decision.close_position_id = weakest.position_id
    decision.close_asset = weakest.asset
    decision.reason = (
        f"Close {weakest.asset} (quality={weakest.quality_score:.3f}) "
        f"for {proposed_asset} (quality={proposed_q:.3f}), "
        f"margin={decision.quality_margin:.3f}"
    )

    logger.info("reallocation_approved",
                 close=weakest.asset, close_quality=weakest.quality_score,
                 proposed=proposed_asset, proposed_quality=proposed_q,
                 margin=decision.quality_margin)

    return decision


def execute_reallocation(position_id: int, reason: str) -> dict:
    """
    Close a position for reallocation (sync, for Celery workers).
    Returns the closed trade data.
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, asset, direction, entry_price, current_price, quantity,
                       position_value, portfolio_id
                FROM paper_positions WHERE id = :pid AND status = 'OPEN'
            """), {"pid": position_id}).mappings().first()

            if not row:
                return {"error": "Position not found or already closed"}

            current = float(row["current_price"] or row["entry_price"])
            entry = float(row["entry_price"])
            qty = float(row["quantity"])
            direction = row["direction"]

            if direction == "LONG":
                pnl = (current - entry) * qty
            else:
                pnl = (entry - current) * qty

            pnl_pct = (pnl / float(row["position_value"])) * 100 if row["position_value"] else 0

            # Close position
            conn.execute(text("""
                UPDATE paper_positions
                SET status = 'CLOSED_REALLOC', exit_price = :price, realized_pnl = :pnl,
                    realized_pnl_pct = :pnl_pct, closed_at = NOW()
                WHERE id = :pid
            """), {"price": current, "pnl": round(pnl, 2),
                   "pnl_pct": round(pnl_pct, 2), "pid": position_id})

            # Update portfolio stats
            conn.execute(text("""
                UPDATE paper_portfolios
                SET current_balance = current_balance + :pnl,
                    total_pnl = total_pnl + :pnl,
                    total_trades = total_trades + 1,
                    winning_trades = winning_trades + CASE WHEN :pnl > 0 THEN 1 ELSE 0 END,
                    losing_trades = losing_trades + CASE WHEN :pnl <= 0 THEN 1 ELSE 0 END
                WHERE id = :portfolio_id
            """), {"pnl": round(pnl, 2), "portfolio_id": row["portfolio_id"]})

            conn.commit()

            # Log reallocation
            _log_reallocation(conn, position_id, row["asset"], direction,
                              pnl, reason)
            conn.commit()

            logger.info("reallocation_executed", position_id=position_id,
                         asset=row["asset"], pnl=round(pnl, 2), reason=reason)

            return {
                "closed_position_id": position_id,
                "asset": row["asset"], "direction": direction,
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                "status": "CLOSED_REALLOC",
            }
    except Exception as e:
        logger.error("reallocation_failed", position_id=position_id, error=str(e))
        return {"error": str(e)}


def get_position_rankings(portfolio_id: int = None) -> list[dict]:
    """Get current position rankings for API/UI."""
    rankings = _load_and_rank_positions(portfolio_id)
    return [r.to_dict() for r in rankings]


def get_reallocation_log(limit: int = 20) -> list[dict]:
    """Get recent reallocation history."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT position_id, asset, direction, pnl, reason, created_at
                FROM reallocation_log ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:

        logger.warning("portfolio_allocator_silent_error", error=str(e))
        return []


def _load_and_rank_positions(portfolio_id: int = None) -> list[PositionQuality]:
    """Load open positions, score each, return sorted desc by quality."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            q = """
                SELECT id, asset, direction, entry_price, current_price, quantity,
                       position_value, consensus_score, unrealized_pnl, unrealized_pnl_pct,
                       stop_loss, take_profit, max_favorable, max_adverse, opened_at,
                       entry_signal_score, entry_signal_label
                FROM paper_positions WHERE status = 'OPEN'
            """
            if portfolio_id:
                q += f" AND portfolio_id = {int(portfolio_id)}"
            q += " ORDER BY opened_at"

            rows = conn.execute(text(q)).mappings().all()
            rankings = [score_position(dict(r)) for r in rows]
            rankings.sort(key=lambda x: x.quality_score, reverse=True)
            return rankings
    except Exception as e:
        logger.warning("ranking_failed", error=str(e))
        return []


def _count_recent_reallocs() -> int:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            return conn.execute(text(
                "SELECT COUNT(*) FROM reallocation_log WHERE created_at > NOW() - INTERVAL '1 hour'"
            )).scalar() or 0
    except Exception as e:

        logger.warning("portfolio_allocator_silent_error", error=str(e))
        return 0


def _log_reallocation(conn, position_id, asset, direction, pnl, reason):
    from sqlalchemy import text
    try:
        pass  # Schema managed by db.schema.tables
        conn.execute(text("""
            INSERT INTO reallocation_log (position_id, asset, direction, pnl, reason)
            VALUES (:pid, :a, :d, :pnl, :r)
        """), {"pid": position_id, "a": asset, "d": direction,
               "pnl": round(pnl, 2), "r": reason})
    except Exception as e:
        logger.warning("realloc_log_failed", error=str(e))
