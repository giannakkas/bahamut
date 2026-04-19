"""
Bahamut.AI — Learning Progress Tracking

Tracks learning milestones based on ACTUAL closed training trades.
Single source: training_trades table + Redis training stats.

Milestones:
  1 trade   → First trade closed
  10 trades → Initial learning
  25 trades → Pattern detection
  50 trades → Calibration ready
  100 trades → Fully trained
"""
import structlog

logger = structlog.get_logger()

MILESTONES = [
    {"label": "First trade closed", "samples": 1},
    {"label": "Initial learning", "samples": 10},
    {"label": "Pattern detection", "samples": 25},
    {"label": "Calibration ready", "samples": 50},
    {"label": "Fully trained", "samples": 100},
]

MIN_SAMPLES_FOR_TRUST = 10
MIN_SAMPLES_FOR_ADAPTIVE = 25


def get_learning_progress() -> dict:
    """Get structured learning progress from real training trade data."""
    data = {
        "status": "warming_up",
        "progress": 0,
        "closed_trades": 0,
        "strategies_active": 0,
        "asset_classes_covered": 0,
        "total_pnl": 0,
        "win_rate": 0,
        "trust_ready": False,
        "adaptive_ready": False,
        "next_milestone": MILESTONES[0]["label"],
        "milestones": [],
        "data_source": "training_trades",
    }

    closed = 0

    # Primary: query training_trades DB table
    try:
        from bahamut.db.query import run_query_one, run_query
        row = run_query_one("SELECT COUNT(*) as cnt FROM training_trades")
        if row:
            closed = int(row.get("cnt", 0))

        if closed > 0:
            stats_row = run_query_one("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(pnl) as total_pnl,
                       COUNT(DISTINCT strategy) as strats,
                       COUNT(DISTINCT asset_class) as classes
                FROM training_trades
            """)
            if stats_row:
                data["closed_trades"] = int(stats_row.get("total", 0))
                wins = int(stats_row.get("wins", 0))
                data["win_rate"] = round(wins / max(1, data["closed_trades"]), 4)
                data["total_pnl"] = round(float(stats_row.get("total_pnl", 0) or 0), 2)
                data["strategies_active"] = int(stats_row.get("strats", 0))
                data["asset_classes_covered"] = int(stats_row.get("classes", 0))
    except Exception as e:
        logger.debug("learning_progress_db_failed", error=str(e))

    # Fallback: Redis training stats (works even without DB)
    if closed == 0:
        try:
            from bahamut.trading.engine import get_training_stats
            stats = get_training_stats()
            closed = stats.get("total_closed_trades", 0)
            data["closed_trades"] = closed
            data["win_rate"] = stats.get("win_rate", 0)
            data["total_pnl"] = stats.get("total_pnl", 0)
            data["data_source"] = "redis_stats"
        except Exception:
            pass

    # Determine status
    data["trust_ready"] = closed >= MIN_SAMPLES_FOR_TRUST
    data["adaptive_ready"] = closed >= MIN_SAMPLES_FOR_ADAPTIVE

    if closed >= 100:
        data["status"] = "ready"
        data["progress"] = 100
    elif closed >= 50:
        data["status"] = "learning"
        data["progress"] = 50 + int((closed - 50) / 50 * 50)
    elif closed >= 10:
        data["status"] = "learning"
        data["progress"] = 10 + int((closed - 10) / 40 * 40)
    elif closed >= 1:
        data["status"] = "warming_up"
        data["progress"] = int(closed / 10 * 10)
    else:
        data["status"] = "warming_up"
        data["progress"] = 0

    # Milestones
    for ms in MILESTONES:
        reached = closed >= ms["samples"]
        data["milestones"].append({
            "label": ms["label"],
            "required": ms["samples"],
            "current": closed,
            "reached": reached,
        })

    # Next milestone
    for ms in MILESTONES:
        if closed < ms["samples"]:
            remaining = ms["samples"] - closed
            data["next_milestone"] = f"{ms['label']} ({remaining} more trades)"
            break
    else:
        data["next_milestone"] = "All milestones reached"

    return data
