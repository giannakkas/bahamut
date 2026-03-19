"""
Bahamut.AI Degraded Mode Tracking

Lightweight mechanism to track which subsystems have failed gracefully.
Used to surface degraded state in API responses without breaking the system.

Usage:
    from bahamut.shared.degraded import mark_degraded, get_degraded_flags, is_degraded

    try:
        result = some_critical_operation()
    except Exception as e:
        mark_degraded("portfolio.kill_switch", str(e))
        logger.error("kill_switch_failed", error=str(e))
        # return safe fallback
"""
import time
import threading
import structlog

logger = structlog.get_logger()

_lock = threading.Lock()
_degraded_flags: dict[str, dict] = {}

# How long a degraded flag persists before auto-clearing (seconds)
FLAG_TTL_SECONDS = 300  # 5 minutes


def mark_degraded(subsystem: str, reason: str, ttl: int = FLAG_TTL_SECONDS) -> None:
    """Mark a subsystem as degraded with a reason and timestamp."""
    with _lock:
        _degraded_flags[subsystem] = {
            "reason": reason[:200],  # truncate
            "since": time.time(),
            "ttl": ttl,
        }
    logger.warning("subsystem_degraded", subsystem=subsystem, reason=reason[:200])


def clear_degraded(subsystem: str) -> None:
    """Clear a degraded flag (subsystem recovered)."""
    with _lock:
        _degraded_flags.pop(subsystem, None)


def is_degraded(subsystem: str) -> bool:
    """Check if a specific subsystem is degraded."""
    with _lock:
        flag = _degraded_flags.get(subsystem)
        if not flag:
            return False
        if time.time() - flag["since"] > flag["ttl"]:
            _degraded_flags.pop(subsystem, None)
            return False
        return True


def get_degraded_flags() -> dict[str, dict]:
    """Get all currently active degraded flags (auto-expires stale ones)."""
    now = time.time()
    with _lock:
        expired = [k for k, v in _degraded_flags.items() if now - v["since"] > v["ttl"]]
        for k in expired:
            del _degraded_flags[k]
        return {k: {"reason": v["reason"], "since": v["since"]} for k, v in _degraded_flags.items()}


def get_system_health_summary() -> dict:
    """Summary for API responses — attach to any endpoint that benefits from it."""
    flags = get_degraded_flags()
    return {
        "degraded": bool(flags),
        "degraded_subsystems": list(flags.keys()),
        "flags": flags,
    }
