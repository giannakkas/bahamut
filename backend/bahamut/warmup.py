"""
Bahamut.AI — Warmup / Bootstrap Calibration Mode

Prevents the engine from behaving as fully calibrated before enough data exists.

Modes:
  - warmup: insufficient data, reduced aggressiveness, no auto-trading
  - active: fully calibrated, all features enabled

Warmup criteria:
  - minimum closed trades
  - minimum calibration age
  - minimum learning samples
"""
import time
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def get_warmup_status() -> dict:
    """Assess current warmup status across all criteria."""
    criteria = {
        "closed_trades": {"required": 20, "current": 0, "met": False},
        "calibration_age_days": {"required": 3, "current": 0, "met": False},
        "learning_samples": {"required": 50, "current": 0, "met": False},
    }

    try:
        from bahamut.db.query import run_query_one

        # Closed trades
        row = run_query_one("SELECT COUNT(*) as cnt FROM paper_positions WHERE status != 'OPEN'")
        if row:
            criteria["closed_trades"]["current"] = int(row.get("cnt", 0))
            criteria["closed_trades"]["met"] = criteria["closed_trades"]["current"] >= criteria["closed_trades"]["required"]

        # Calibration age (days since first signal cycle)
        row = run_query_one("SELECT MIN(started_at) as first_cycle FROM signal_cycles")
        if row and row.get("first_cycle"):
            first = row["first_cycle"]
            if isinstance(first, str):
                first = datetime.fromisoformat(first.replace("Z", "+00:00"))
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - first).days
            criteria["calibration_age_days"]["current"] = age_days
            criteria["calibration_age_days"]["met"] = age_days >= criteria["calibration_age_days"]["required"]

        # Learning samples
        row = run_query_one("SELECT COUNT(*) as cnt FROM learning_events")
        if row:
            criteria["learning_samples"]["current"] = int(row.get("cnt", 0))
            criteria["learning_samples"]["met"] = criteria["learning_samples"]["current"] >= criteria["learning_samples"]["required"]

    except Exception as e:
        logger.warning("warmup_status_check_failed", error=str(e))

    all_met = all(c["met"] for c in criteria.values())
    met_count = sum(1 for c in criteria.values() if c["met"])
    total = len(criteria)
    progress = round(met_count / total, 2) if total > 0 else 0

    mode = "active" if all_met else "warmup"

    return {
        "mode": mode,
        "progress": progress,
        "criteria": criteria,
        "met_count": met_count,
        "total_criteria": total,
        "message": _get_warmup_message(mode, criteria),
    }


def is_warmup_mode() -> bool:
    """Quick check: is the system still in warmup?"""
    try:
        status = get_warmup_status()
        return status["mode"] == "warmup"
    except Exception:
        return True  # fail-safe: assume warmup if check fails


def get_warmup_size_multiplier() -> float:
    """During warmup, reduce position sizes."""
    if is_warmup_mode():
        return 0.5
    return 1.0


def _get_warmup_message(mode: str, criteria: dict) -> str:
    if mode == "active":
        return "System fully calibrated and ready for trading"

    missing = []
    for key, c in criteria.items():
        if not c["met"]:
            label = key.replace("_", " ").title()
            missing.append(f"{label}: {c['current']}/{c['required']}")

    return f"System is warming up. Still needed: {', '.join(missing)}"
