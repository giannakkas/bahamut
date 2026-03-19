"""
Bahamut.AI — Learning Progress Tracking

Provides structured visibility into the system's learning state,
replacing opaque "no patterns yet" with meaningful progress indicators.
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


def get_learning_progress() -> dict:
    """Get structured learning progress data."""
    data = {
        "status": "warming_up",
        "progress": 0,
        "patterns_detected": 0,
        "samples_collected": 0,
        "closed_trades": 0,
        "next_milestone": MILESTONES[0]["label"],
        "milestones": [],
    }

    try:
        from bahamut.db.query import run_query_one

        # Samples (learning events)
        row = run_query_one("SELECT COUNT(*) as cnt FROM learning_events")
        samples = int(row.get("cnt", 0)) if row else 0
        data["samples_collected"] = samples

        # Patterns (adaptive rules)
        row = run_query_one("SELECT COUNT(*) as cnt FROM portfolio_adaptive_rules WHERE active = TRUE")
        patterns = int(row.get("cnt", 0)) if row else 0
        data["patterns_detected"] = patterns

        # Closed trades
        row = run_query_one("SELECT COUNT(*) as cnt FROM paper_positions WHERE status != 'OPEN'")
        closed = int(row.get("cnt", 0)) if row else 0
        data["closed_trades"] = closed

    except Exception as e:
        logger.warning("learning_progress_failed", error=str(e))

    samples = data["samples_collected"]

    # Determine status
    if samples >= 100:
        data["status"] = "ready"
        data["progress"] = 100
    elif samples >= 50:
        data["status"] = "learning"
        data["progress"] = 50 + int((samples - 50) / 50 * 50)
    elif samples >= 10:
        data["status"] = "learning"
        data["progress"] = 10 + int((samples - 10) / 40 * 40)
    elif samples >= 1:
        data["status"] = "warming_up"
        data["progress"] = int(samples / 10 * 10)
    else:
        data["status"] = "warming_up"
        data["progress"] = 0

    # Milestones
    for ms in MILESTONES:
        reached = samples >= ms["samples"]
        data["milestones"].append({
            "label": ms["label"],
            "required": ms["samples"],
            "reached": reached,
        })
        if not reached and data["next_milestone"] == MILESTONES[0]["label"]:
            data["next_milestone"] = f"{ms['label']} ({ms['samples']} samples)"

    # Find actual next milestone
    for ms in MILESTONES:
        if samples < ms["samples"]:
            data["next_milestone"] = f"{ms['label']} ({ms['samples']} samples)"
            break
    else:
        data["next_milestone"] = "All milestones reached"

    return data
