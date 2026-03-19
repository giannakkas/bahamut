"""
Bahamut.AI — Kill Switch Recovery Intelligence

Manages recovery after kill switch activation:
  - Cooldown window (minimum wait before re-entry)
  - Gradual re-entry (reduced size, higher confidence required)
  - Automatic recovery when risk normalizes

Still fail-closed: never bypasses safety.
"""
import time
import structlog

logger = structlog.get_logger()

# Recovery parameters
COOLDOWN_SECONDS = 900       # 15 minutes minimum cooldown
RECOVERY_SIZE_MULT = 0.5     # 50% position size during recovery
RECOVERY_CONFIDENCE_BOOST = 0.10  # require 10% higher confidence during recovery

# In-memory state (persists across requests within the same worker process)
_recovery_state = {
    "last_triggered_at": 0,
    "trigger_count_today": 0,
    "recovery_mode": False,
    "recovery_started_at": 0,
}


def record_kill_switch_trigger():
    """Called when kill switch activates."""
    _recovery_state["last_triggered_at"] = time.time()
    _recovery_state["trigger_count_today"] += 1
    _recovery_state["recovery_mode"] = False
    logger.warning("kill_switch_trigger_recorded",
                    count_today=_recovery_state["trigger_count_today"])


def get_recovery_status() -> dict:
    """Get current kill switch recovery status."""
    now = time.time()
    last = _recovery_state["last_triggered_at"]

    if last == 0:
        return {
            "status": "normal",
            "kill_switch_active": False,
            "in_cooldown": False,
            "in_recovery": False,
            "cooldown_remaining_seconds": 0,
            "trigger_count_today": 0,
            "size_multiplier": 1.0,
            "confidence_boost": 0,
            "message": "System operating normally — no recent kill switch events",
        }

    elapsed = now - last
    in_cooldown = elapsed < COOLDOWN_SECONDS
    cooldown_remaining = max(0, int(COOLDOWN_SECONDS - elapsed))

    # Check if risk has normalized (check current kill switch state)
    current_ks_active = False
    try:
        from bahamut.portfolio.kill_switch import get_current_state
        ks = get_current_state()
        current_ks_active = ks.get("kill_switch_active", False)
    except Exception:
        current_ks_active = True  # fail-closed

    if current_ks_active:
        return {
            "status": "active",
            "kill_switch_active": True,
            "in_cooldown": False,
            "in_recovery": False,
            "cooldown_remaining_seconds": 0,
            "trigger_count_today": _recovery_state["trigger_count_today"],
            "size_multiplier": 0,
            "confidence_boost": 0,
            "message": "Kill switch ACTIVE — all new trades blocked",
        }

    if in_cooldown:
        return {
            "status": "cooldown",
            "kill_switch_active": False,
            "in_cooldown": True,
            "in_recovery": False,
            "cooldown_remaining_seconds": cooldown_remaining,
            "trigger_count_today": _recovery_state["trigger_count_today"],
            "size_multiplier": 0,
            "confidence_boost": 0,
            "message": f"Cooldown active — {cooldown_remaining}s remaining before re-entry",
        }

    # Post-cooldown: gradual recovery phase (30 minutes after cooldown)
    recovery_window = COOLDOWN_SECONDS + 1800  # 15min cooldown + 30min recovery
    if elapsed < recovery_window:
        progress = (elapsed - COOLDOWN_SECONDS) / 1800  # 0 to 1
        size_mult = RECOVERY_SIZE_MULT + (1.0 - RECOVERY_SIZE_MULT) * progress
        conf_boost = RECOVERY_CONFIDENCE_BOOST * (1.0 - progress)
        return {
            "status": "recovering",
            "kill_switch_active": False,
            "in_cooldown": False,
            "in_recovery": True,
            "cooldown_remaining_seconds": 0,
            "recovery_progress": round(progress, 2),
            "trigger_count_today": _recovery_state["trigger_count_today"],
            "size_multiplier": round(size_mult, 2),
            "confidence_boost": round(conf_boost, 3),
            "message": f"Gradual recovery — {progress:.0%} complete, size ×{size_mult:.2f}",
        }

    # Fully recovered
    return {
        "status": "recovered",
        "kill_switch_active": False,
        "in_cooldown": False,
        "in_recovery": False,
        "cooldown_remaining_seconds": 0,
        "trigger_count_today": _recovery_state["trigger_count_today"],
        "size_multiplier": 1.0,
        "confidence_boost": 0,
        "message": "Fully recovered from last kill switch event",
    }


def get_recovery_size_multiplier() -> float:
    """Get current position size multiplier accounting for recovery state."""
    status = get_recovery_status()
    return status.get("size_multiplier", 1.0)


def get_recovery_confidence_boost() -> float:
    """Get additional confidence requirement during recovery."""
    status = get_recovery_status()
    return status.get("confidence_boost", 0)
