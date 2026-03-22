"""
Bahamut.AI Degraded Mode Tracking

Tracks which subsystems have failed gracefully.
All state persisted to Redis for cross-process visibility.

Usage:
    from bahamut.shared.degraded import mark_degraded, get_degraded_flags, is_degraded
"""
import json
import os
import time
import threading
import structlog

logger = structlog.get_logger()

FLAG_TTL_SECONDS = 300  # 5 minutes


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def mark_degraded(subsystem: str, reason: str, ttl: int = FLAG_TTL_SECONDS) -> None:
    """Mark a subsystem as degraded. Writes to Redis for cross-process visibility."""
    data = {"reason": reason[:200], "since": time.time(), "ttl": ttl}
    r = _get_redis()
    if r:
        try:
            r.hset("bahamut:degraded_flags", subsystem, json.dumps(data))
        except Exception:
            pass
    logger.warning("subsystem_degraded", subsystem=subsystem, reason=reason[:200])


def clear_degraded(subsystem: str) -> None:
    """Clear a degraded flag (subsystem recovered)."""
    r = _get_redis()
    if r:
        try:
            r.hdel("bahamut:degraded_flags", subsystem)
        except Exception:
            pass


def is_degraded(subsystem: str) -> bool:
    """Check if a specific subsystem is degraded. Reads from Redis."""
    r = _get_redis()
    if not r:
        return False
    try:
        raw = r.hget("bahamut:degraded_flags", subsystem)
        if not raw:
            return False
        flag = json.loads(raw)
        if time.time() - flag["since"] > flag.get("ttl", FLAG_TTL_SECONDS):
            r.hdel("bahamut:degraded_flags", subsystem)
            return False
        return True
    except Exception:
        return False


def get_degraded_flags() -> dict[str, dict]:
    """Get all currently active degraded flags. Reads from Redis."""
    now = time.time()
    r = _get_redis()
    if not r:
        return {}
    try:
        raw = r.hgetall("bahamut:degraded_flags")
        result = {}
        expired = []
        for k, v in raw.items():
            key = k.decode() if isinstance(k, bytes) else k
            flag = json.loads(v)
            if now - flag["since"] > flag.get("ttl", FLAG_TTL_SECONDS):
                expired.append(key)
            else:
                result[key] = {"reason": flag["reason"], "since": flag["since"]}
        for key in expired:
            r.hdel("bahamut:degraded_flags", key)
        return result
    except Exception:
        return {}


def get_system_health_summary() -> dict:
    """Summary for API responses."""
    flags = get_degraded_flags()
    return {
        "degraded": bool(flags),
        "degraded_subsystems": list(flags.keys()),
        "flags": flags,
    }
