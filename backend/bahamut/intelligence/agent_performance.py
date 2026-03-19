"""
Bahamut.AI — Agent Performance Tracking & Ranking

Tracks per-agent performance metrics and computes a composite score
used for confidence weighting and the agent leaderboard.

Score = weighted function of:
  - profitability (30%)
  - stability/consistency (20%)
  - risk-adjusted return (25%)
  - recent performance (25%)
"""
import structlog

logger = structlog.get_logger()

AGENT_IDS = [
    "technical_agent", "sentiment_agent", "macro_agent",
    "risk_agent", "volatility_agent", "liquidity_agent",
]

# Tier thresholds
TIER_THRESHOLDS = {
    "A": 0.75,
    "B": 0.55,
    "C": 0.35,
}


def get_agent_leaderboard() -> list[dict]:
    """Compute agent rankings from performance data."""
    agents = []
    for agent_id in AGENT_IDS:
        stats = _get_agent_stats(agent_id)
        score = _compute_agent_score(stats)
        tier = _score_to_tier(score)
        agents.append({
            "agent_id": agent_id,
            "name": agent_id.replace("_", " ").title(),
            "total_trades": stats["total_trades"],
            "win_rate": round(stats["win_rate"], 3),
            "avg_return": round(stats["avg_return"], 4),
            "consistency": round(stats["consistency"], 3),
            "recent_performance": round(stats["recent_perf"], 3),
            "composite_score": round(score, 3),
            "tier": tier,
        })

    agents.sort(key=lambda a: a["composite_score"], reverse=True)
    for i, a in enumerate(agents):
        a["rank"] = i + 1

    return agents


def get_agent_score(agent_id: str) -> float:
    """Get composite score for a single agent (used in confidence weighting)."""
    stats = _get_agent_stats(agent_id)
    return _compute_agent_score(stats)


def _get_agent_stats(agent_id: str) -> dict:
    """Load agent performance stats from DB."""
    defaults = {
        "total_trades": 0, "win_rate": 0.5, "avg_return": 0,
        "consistency": 0.5, "recent_perf": 0.5,
        "correct_signals": 0, "wrong_signals": 0,
        "profit_factor": 1.0, "current_streak": 0,
    }
    try:
        from bahamut.db.query import run_query_one, run_query
        # Aggregate from agent_trade_performance
        row = run_query_one("""
            SELECT SUM(total_signals) as total, SUM(correct_signals) as correct,
                   SUM(wrong_signals) as wrong, AVG(accuracy) as accuracy,
                   AVG(profit_factor) as pf, MAX(current_streak) as streak
            FROM agent_trade_performance WHERE agent_name = :a
        """, {"a": agent_id})

        if row and row.get("total"):
            total = int(row["total"])
            correct = int(row.get("correct", 0))
            wrong = int(row.get("wrong", 0))
            defaults["total_trades"] = total
            defaults["win_rate"] = correct / max(total, 1)
            defaults["profit_factor"] = float(row.get("pf", 1.0) or 1.0)
            defaults["current_streak"] = int(row.get("streak", 0) or 0)

        # Recent performance from learning events (last 20 trades)
        recent = run_query("""
            SELECT was_correct, trust_delta FROM learning_events
            WHERE agent_name = :a ORDER BY created_at DESC LIMIT 20
        """, {"a": agent_id})

        if recent:
            recent_correct = sum(1 for r in recent if r.get("was_correct"))
            defaults["recent_perf"] = recent_correct / len(recent)
            # Consistency = 1 - stddev of results (normalized)
            deltas = [abs(float(r.get("trust_delta", 0) or 0)) for r in recent]
            if deltas:
                avg_delta = sum(deltas) / len(deltas)
                variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)
                defaults["consistency"] = max(0, 1.0 - (variance ** 0.5) * 10)

        # Avg return from positions
        ret_row = run_query_one("""
            SELECT AVG(le.position_pnl_pct) as avg_ret
            FROM learning_events le WHERE le.agent_name = :a AND le.position_pnl_pct IS NOT NULL
        """, {"a": agent_id})
        if ret_row and ret_row.get("avg_ret") is not None:
            defaults["avg_return"] = float(ret_row["avg_ret"])

    except Exception as e:
        logger.warning("agent_stats_load_failed", agent=agent_id, error=str(e))

    return defaults


def _compute_agent_score(stats: dict) -> float:
    """Compute composite score from 0 to 1."""
    profitability = min(1.0, max(0, stats["win_rate"]))
    stability = min(1.0, max(0, stats["consistency"]))
    risk_adj = min(1.0, max(0, (stats["profit_factor"] - 0.5) / 2.0))
    recent = min(1.0, max(0, stats["recent_perf"]))

    score = (
        0.30 * profitability +
        0.20 * stability +
        0.25 * risk_adj +
        0.25 * recent
    )
    return min(1.0, max(0, score))


def _score_to_tier(score: float) -> str:
    if score >= TIER_THRESHOLDS["A"]:
        return "A"
    elif score >= TIER_THRESHOLDS["B"]:
        return "B"
    elif score >= TIER_THRESHOLDS["C"]:
        return "C"
    return "D"
