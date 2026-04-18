"""Tracks engine-side rejections of selector EXECUTE decisions.

The selector tags candidates EXECUTE before the engine's final gauntlet of
checks (sentiment gate, circuit breaker, per-strategy DD, composite floor,
broker availability, etc.). When the engine rejects, that reason is lost
to the dashboard.

This module records every post-selector rejection with enough context that
the dashboard can show "selector said EXECUTE, engine rejected because X"
side by side.
"""
import os
import time
import json
import structlog

logger = structlog.get_logger()

_REDIS_KEY_PREFIX = "bahamut:engine_rejection:"
_LIST_KEY = "bahamut:engine_rejections:recent"
_TTL = 3600  # 1 hour — covers multiple cycles


def _r():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
    except Exception:
        return None


def record_rejection(
    asset: str,
    strategy: str,
    direction: str,
    signal_id: str,
    reason_code: str,
    reason_detail: str = "",
    extra: dict | None = None,
) -> None:
    """Record that the engine rejected a selector EXECUTE decision.

    reason_code: one of
      - sentiment_long_block / sentiment_short_block
      - circuit_breaker_open
      - exec_lock_held
      - composite_floor
      - broker_unavailable
      - strategy_dd_block
      - kill_switch_active
      - shutdown_in_progress
      - phantom_internal_abort
      - execution_error
      - execution_exception
      - price_staleness
      - other
    """
    r = _r()
    if not r:
        return
    entry = {
        "ts": time.time(),
        "asset": asset,
        "strategy": strategy,
        "direction": direction,
        "signal_id": signal_id,
        "reason_code": reason_code,
        "reason_detail": (reason_detail or "")[:300],
    }
    if extra:
        entry["extra"] = {
            k: (str(v)[:100] if not isinstance(v, (int, float, bool)) else v)
            for k, v in extra.items()
        }
    try:
        r.setex(f"{_REDIS_KEY_PREFIX}{signal_id}", _TTL,
                json.dumps(entry, default=str))
        r.lpush(_LIST_KEY, json.dumps(entry, default=str))
        r.ltrim(_LIST_KEY, 0, 199)
        r.expire(_LIST_KEY, _TTL)
    except Exception as e:
        logger.debug("rejection_tracker_write_failed", error=str(e)[:100])


def get_recent_rejections(limit: int = 50) -> list[dict]:
    """Return recent engine rejections, most recent first."""
    r = _r()
    if not r:
        return []
    try:
        raw = r.lrange(_LIST_KEY, 0, max(0, limit - 1))
        out = []
        for item in raw:
            try:
                if isinstance(item, bytes):
                    item = item.decode()
                out.append(json.loads(item))
            except Exception:
                continue
        return out
    except Exception:
        return []


def get_rejection_for_signal(signal_id: str) -> dict | None:
    """Look up rejection reason for a specific signal."""
    r = _r()
    if not r:
        return None
    try:
        raw = r.get(f"{_REDIS_KEY_PREFIX}{signal_id}")
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)
    except Exception:
        return None
