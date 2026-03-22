"""
Bahamut.AI — System Readiness Gate

Single source of truth for "is it safe to open new trades?"

State stored in Redis for cross-process visibility + in-memory fallback
when Redis is unavailable (tests, startup race).

Called by:
  - ExecutionEngine.submit_signal() — blocks new orders if unsafe
  - Orchestrator — skips signal generation if unsafe
  - Dashboard API — surfaces current readiness state
"""
import json
import os
import time
import structlog

logger = structlog.get_logger()

MAX_DATA_AGE_SECONDS = 21600
REDIS_KEY = "bahamut:system_readiness"

# Test override: when True, can_system_trade() always returns (True, []).
_test_override_allow = False

# In-memory fallback: updated alongside Redis, used when Redis is down.
_mem_state: dict = {}


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _write_state(updates: dict):
    """Write to Redis + in-memory fallback."""
    _mem_state.update(updates)
    r = _get_redis()
    if r:
        try:
            for k, v in updates.items():
                r.hset(REDIS_KEY, k, json.dumps(v))
        except Exception:
            pass


def _read_state() -> dict:
    """Read from Redis first, fall back to in-memory."""
    r = _get_redis()
    if r:
        try:
            raw = r.hgetall(REDIS_KEY)
            if raw:
                result = {
                    (k.decode() if isinstance(k, bytes) else k): json.loads(v)
                    for k, v in raw.items()
                }
                _mem_state.update(result)  # sync local cache
                return result
        except Exception:
            pass
    return dict(_mem_state)


def _clear_state():
    """Clear all state (for tests)."""
    _mem_state.clear()
    r = _get_redis()
    if r:
        try:
            r.delete(REDIS_KEY)
        except Exception:
            pass


# ═══════════════════════════════════════════
# RECONCILIATION
# ═══════════════════════════════════════════

def mark_reconciliation_success():
    _write_state({"reconciliation_complete": True, "reconciliation_error": ""})

def mark_reconciliation_failed(error: str):
    _write_state({"reconciliation_complete": False, "reconciliation_error": error[:200]})

def is_reconciled() -> bool:
    return _read_state().get("reconciliation_complete", False)


# ═══════════════════════════════════════════
# DB HEALTH
# ═══════════════════════════════════════════

def mark_db_ok():
    _write_state({"db_last_ok": time.time(), "db_last_error": ""})

def mark_db_error(error: str):
    _write_state({"db_last_error": error[:200]})

def is_db_healthy() -> bool:
    state = _read_state()
    last_ok = state.get("db_last_ok", 0)
    return last_ok > 0 and (time.time() - last_ok) < 120


# ═══════════════════════════════════════════
# DATA FRESHNESS
# ═══════════════════════════════════════════

def update_asset_data_health(asset: str, status: str, age_seconds: int = None):
    _write_state({f"data:{asset}": {
        "status": status, "age_seconds": age_seconds, "updated_at": time.time(),
    }})

def is_asset_data_fresh(asset: str) -> bool:
    health = _read_state().get(f"data:{asset}")
    if not health:
        return False
    if health["status"] in ("STALE", "MISSING"):
        return False
    if health.get("age_seconds") is not None and health["age_seconds"] > MAX_DATA_AGE_SECONDS:
        return False
    return True


# ═══════════════════════════════════════════
# CANONICAL GATE
# ═══════════════════════════════════════════

def can_system_trade(asset: str = "") -> tuple[bool, list[str]]:
    """Check if the system is ready to open new trades."""
    if _test_override_allow:
        return (True, [])

    state = _read_state()
    reasons = []

    if not state.get("reconciliation_complete", False):
        err = state.get("reconciliation_error", "startup pending")
        reasons.append(f"ENGINE_NOT_RECONCILED: {err}")

    if asset:
        health = state.get(f"data:{asset}")
        if not health:
            reasons.append(f"DATA_NOT_FRESH: {asset} status=UNKNOWN (no data recorded)")
        elif health.get("status") in ("STALE", "MISSING"):
            reasons.append(f"DATA_NOT_FRESH: {asset} status={health['status']} age={health.get('age_seconds', '?')}s")
        elif health.get("age_seconds") is not None and health["age_seconds"] > MAX_DATA_AGE_SECONDS:
            reasons.append(f"DATA_NOT_FRESH: {asset} age={health['age_seconds']}s > {MAX_DATA_AGE_SECONDS}s")

    return (len(reasons) == 0, reasons)


def get_readiness_state() -> dict:
    """Full readiness state for dashboard API."""
    state = _read_state()
    can_trade, reasons = can_system_trade()

    asset_readiness = {}
    for key, val in state.items():
        if key.startswith("data:"):
            asset = key[5:]
            asset_can, asset_reasons = can_system_trade(asset=asset)
            asset_readiness[asset] = {
                "can_trade": asset_can,
                "data_status": val.get("status", "UNKNOWN"),
                "data_age_seconds": val.get("age_seconds"),
                "reasons": asset_reasons,
            }

    return {
        "can_trade": can_trade,
        "reasons": reasons,
        "reconciliation_complete": state.get("reconciliation_complete", False),
        "reconciliation_error": state.get("reconciliation_error") or None,
        "db_healthy": is_db_healthy(),
        "db_last_ok_ago": round(time.time() - state.get("db_last_ok", 0), 1) if state.get("db_last_ok", 0) > 0 else None,
        "assets": asset_readiness,
    }
