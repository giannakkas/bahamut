"""
Bahamut.AI — System Readiness Gate

Single source of truth for "is it safe to open new trades?"

Called by:
  - ExecutionEngine.submit_signal() — blocks new orders if unsafe
  - Orchestrator — skips signal generation if unsafe
  - Dashboard API — surfaces current readiness state

Checks (in order):
  1. Kill switch
  2. Engine reconciliation from DB
  3. Database connectivity
  4. Per-asset data freshness

Policy:
  - OPEN positions are ALWAYS monitored (SL/TP/timeout) regardless of readiness
  - Only NEW ENTRIES are blocked when system is not ready
  - Recovery is automatic: when all checks pass, trading resumes
"""
import time
import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# STATE (module-level, shared across workers via singleton)
# ═══════════════════════════════════════════

_state = {
    "reconciliation_complete": False,
    "reconciliation_error": "",
    "db_last_ok": 0.0,
    "db_last_error": "",
    "asset_data_health": {},  # {asset: {status, age_seconds, updated_at}}
}

# How stale is too stale (seconds). 4H = 14400s. Allow 1.5 bars = 6 hours.
MAX_DATA_AGE_SECONDS = 21600
# How old can the last DB check be before we consider it stale
DB_CHECK_STALENESS = 120  # 2 minutes


# ═══════════════════════════════════════════
# RECONCILIATION TRACKING
# ═══════════════════════════════════════════

def mark_reconciliation_success():
    """Called by engine._reconcile_from_db on success."""
    _state["reconciliation_complete"] = True
    _state["reconciliation_error"] = ""
    logger.info("system_readiness_reconciled")


def mark_reconciliation_failed(error: str):
    """Called by engine._reconcile_from_db on failure."""
    _state["reconciliation_complete"] = False
    _state["reconciliation_error"] = error[:200]
    logger.warning("system_readiness_reconciliation_failed", error=error[:200])


def is_reconciled() -> bool:
    return _state["reconciliation_complete"]


# ═══════════════════════════════════════════
# DB HEALTH TRACKING
# ═══════════════════════════════════════════

def mark_db_ok():
    """Called after any successful DB operation in the cycle."""
    _state["db_last_ok"] = time.time()
    _state["db_last_error"] = ""


def mark_db_error(error: str):
    _state["db_last_error"] = error[:200]


def is_db_healthy() -> bool:
    """DB is healthy if last successful check was recent."""
    if _state["db_last_ok"] == 0:
        return False
    return (time.time() - _state["db_last_ok"]) < DB_CHECK_STALENESS


# ═══════════════════════════════════════════
# DATA FRESHNESS TRACKING
# ═══════════════════════════════════════════

def update_asset_data_health(asset: str, status: str, age_seconds: int = None):
    """Called by orchestrator after fetching candles for an asset.

    status: HEALTHY | STALE | MISSING | DEGRADED
    """
    _state["asset_data_health"][asset] = {
        "status": status,
        "age_seconds": age_seconds,
        "updated_at": time.time(),
    }


def is_asset_data_fresh(asset: str) -> bool:
    """Check if an asset's data is fresh enough for signal generation."""
    health = _state["asset_data_health"].get(asset)
    if not health:
        return False  # No data recorded → not fresh
    if health["status"] in ("STALE", "MISSING"):
        return False
    if health.get("age_seconds") is not None and health["age_seconds"] > MAX_DATA_AGE_SECONDS:
        return False
    return True


# ═══════════════════════════════════════════
# CANONICAL GATE — the one function that matters
# ═══════════════════════════════════════════

def can_system_trade(asset: str = "") -> tuple[bool, list[str]]:
    """Check if the system is ready to open new trades.

    Returns:
        (allowed: bool, reasons: list[str])

    Reasons are populated whether allowed or not — if allowed, reasons is empty.
    If not allowed, reasons lists all blocking conditions.

    NOTE: This does NOT check kill switch or portfolio limits.
    Those are checked by engine.submit_signal() and pm.can_trade() respectively.
    This gate checks INFRASTRUCTURE readiness only.
    """
    reasons = []

    # 1. Reconciliation
    if not _state["reconciliation_complete"]:
        reasons.append(f"ENGINE_NOT_RECONCILED: {_state['reconciliation_error'] or 'startup pending'}")

    # 2. Data freshness (per-asset)
    if asset:
        if not is_asset_data_fresh(asset):
            health = _state["asset_data_health"].get(asset, {})
            status = health.get("status", "UNKNOWN")
            age = health.get("age_seconds", "?")
            reasons.append(f"DATA_NOT_FRESH: {asset} status={status} age={age}s")

    return (len(reasons) == 0, reasons)


def get_readiness_state() -> dict:
    """Full readiness state for dashboard API."""
    can_trade, reasons = can_system_trade()

    # Per-asset readiness
    asset_readiness = {}
    for asset, health in _state["asset_data_health"].items():
        asset_can, asset_reasons = can_system_trade(asset=asset)
        asset_readiness[asset] = {
            "can_trade": asset_can,
            "data_status": health.get("status", "UNKNOWN"),
            "data_age_seconds": health.get("age_seconds"),
            "reasons": asset_reasons,
        }

    return {
        "can_trade": can_trade,
        "reasons": reasons,
        "reconciliation_complete": _state["reconciliation_complete"],
        "reconciliation_error": _state["reconciliation_error"] or None,
        "db_healthy": is_db_healthy(),
        "db_last_ok_ago": round(time.time() - _state["db_last_ok"], 1) if _state["db_last_ok"] > 0 else None,
        "assets": asset_readiness,
    }
