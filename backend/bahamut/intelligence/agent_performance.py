"""
Bahamut.AI — Strategy Performance Tracking & Ranking

Ranks strategies (v5_base, v5_tuned, v9_breakout) based on ACTUAL
closed training trade outcomes. Replaces old agent-based leaderboard.

Data source: training_trades table + Redis training stats.

Score = weighted function of:
  - win_rate (30%)
  - profit_factor (25%)
  - consistency (20%)
  - recent_performance (25%)

Below MIN_SAMPLES, all values are marked PROVISIONAL.
"""
import structlog

logger = structlog.get_logger()

STRATEGY_IDS = ["v5_base", "v5_tuned", "v9_breakout"]
MIN_SAMPLES = 10  # Minimum trades before trust is computed

TIER_THRESHOLDS = {"A": 0.75, "B": 0.55, "C": 0.35}


def get_agent_leaderboard() -> list[dict]:
    """Compute strategy rankings from real training trade data.
    Named 'agent_leaderboard' for backward compat with existing API."""
    strategies = []
    for strat_id in STRATEGY_IDS:
        stats = _get_strategy_stats(strat_id)
        provisional = stats["total_trades"] < MIN_SAMPLES
        score = _compute_score(stats) if not provisional else 0.5
        tier = _score_to_tier(score) if not provisional else "—"

        strategies.append({
            "agent_id": strat_id,  # backward compat field name
            "name": _format_name(strat_id),
            "total_trades": stats["total_trades"],
            "win_rate": round(stats["win_rate"], 3),
            "avg_pnl": round(stats["avg_pnl"], 2),
            "profit_factor": round(stats["profit_factor"], 2),
            "consistency": round(stats["consistency"], 3),
            "recent_performance": round(stats["recent_perf"], 3),
            "composite_score": round(score, 3),
            "tier": tier,
            "provisional": provisional,
            "min_samples": MIN_SAMPLES,
            "data_source": "training_trades",
        })

    strategies.sort(key=lambda s: s["composite_score"], reverse=True)
    for i, s in enumerate(strategies):
        s["rank"] = i + 1

    return strategies


def get_strategy_trust(strategy: str) -> dict:
    """Get trust score for a strategy. Returns provisional flag if insufficient data."""
    stats = _get_strategy_stats(strategy)
    provisional = stats["total_trades"] < MIN_SAMPLES

    if provisional:
        return {
            "strategy": strategy,
            "trust_score": 0.5,
            "trust_label": "provisional",
            "trades": stats["total_trades"],
            "min_required": MIN_SAMPLES,
            "provisional": True,
        }

    score = _compute_score(stats)
    if score >= 0.7:
        label = "high"
    elif score >= 0.5:
        label = "moderate"
    elif score >= 0.3:
        label = "low"
    else:
        label = "untrusted"

    return {
        "strategy": strategy,
        "trust_score": round(score, 3),
        "trust_label": label,
        "trades": stats["total_trades"],
        "win_rate": round(stats["win_rate"], 3),
        "profit_factor": round(stats["profit_factor"], 2),
        "provisional": False,
    }


def _get_strategy_stats(strategy: str) -> dict:
    """Load strategy stats from training_trades DB, fallback to Redis."""
    defaults = {
        "total_trades": 0, "win_rate": 0.5, "avg_pnl": 0,
        "profit_factor": 1.0, "consistency": 0.5, "recent_perf": 0.5,
        "wins": 0, "losses": 0, "gross_profit": 0, "gross_loss": 0,
    }

    # Try DB first (most accurate)
    try:
        from bahamut.db.query import run_query_one, run_query

        row = run_query_one("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                   AVG(pnl) as avg_pnl,
                   SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as gross_profit,
                   SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as gross_loss
            FROM training_trades WHERE strategy = :s
        """, {"s": strategy})

        if row and int(row.get("total", 0)) > 0:
            total = int(row["total"])
            wins = int(row.get("wins", 0))
            defaults["total_trades"] = total
            defaults["wins"] = wins
            defaults["losses"] = int(row.get("losses", 0))
            defaults["win_rate"] = wins / max(total, 1)
            defaults["avg_pnl"] = float(row.get("avg_pnl", 0) or 0)
            gp = float(row.get("gross_profit", 0) or 0)
            gl = float(row.get("gross_loss", 0) or 0)
            defaults["gross_profit"] = gp
            defaults["gross_loss"] = gl
            defaults["profit_factor"] = gp / max(gl, 0.01)

        # Recent 10 trades for consistency + recent perf
        recent = run_query("""
            SELECT pnl FROM training_trades
            WHERE strategy = :s ORDER BY created_at DESC LIMIT 10
        """, {"s": strategy})

        if recent:
            recent_pnls = [float(r.get("pnl", 0)) for r in recent]
            recent_wins = sum(1 for p in recent_pnls if p > 0)
            defaults["recent_perf"] = recent_wins / len(recent_pnls)

            # Consistency = 1 - normalized stddev of PnL
            if len(recent_pnls) >= 3:
                avg = sum(recent_pnls) / len(recent_pnls)
                variance = sum((p - avg) ** 2 for p in recent_pnls) / len(recent_pnls)
                stddev = variance ** 0.5
                # Normalize: stddev of $100 on $500 risk → 0.2 → consistency 0.8
                norm_std = min(1.0, stddev / max(abs(avg), 50))
                defaults["consistency"] = max(0, 1.0 - norm_std)

        return defaults

    except Exception as e:
        logger.debug("strategy_stats_db_failed", strategy=strategy, error=str(e))

    # Fallback: Redis training stats
    try:
        import os, json, redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get(f"bahamut:training:strategy_stats:{strategy}")
        if raw:
            s = json.loads(raw)
            defaults["total_trades"] = s.get("trades", 0)
            defaults["wins"] = s.get("wins", 0)
            defaults["losses"] = s.get("losses", 0)
            defaults["win_rate"] = s.get("win_rate", 0.5)
            defaults["avg_pnl"] = s.get("total_pnl", 0) / max(s.get("trades", 1), 1)
    except Exception:
        pass

    return defaults


def _compute_score(stats: dict) -> float:
    """Composite score from 0 to 1."""
    wr = min(1.0, max(0, stats["win_rate"]))
    pf = min(1.0, max(0, (stats["profit_factor"] - 0.5) / 2.5))  # PF 0.5→0, PF 3→1
    cons = min(1.0, max(0, stats["consistency"]))
    recent = min(1.0, max(0, stats["recent_perf"]))

    return 0.30 * wr + 0.25 * pf + 0.20 * cons + 0.25 * recent


def _score_to_tier(score: float) -> str:
    if score >= TIER_THRESHOLDS["A"]:
        return "A"
    if score >= TIER_THRESHOLDS["B"]:
        return "B"
    if score >= TIER_THRESHOLDS["C"]:
        return "C"
    return "D"


def _format_name(strat: str) -> str:
    return strat.replace("_", " ").title()
