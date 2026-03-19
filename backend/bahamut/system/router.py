"""
Bahamut.AI System Health Endpoint (Phase 2)

Reports:
  - Core system status (healthy / degraded / critical)
  - Database connectivity + latency
  - Redis connectivity + latency
  - Degraded subsystems with severity level
  - Schema version
  - Celery queue backlog (if available)
"""
import time
import structlog
from fastapi import APIRouter

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health")
async def system_health():
    """
    GET /api/v1/system/health

    Returns comprehensive system health with latency measurements.
    """
    start = time.monotonic()
    checks = {}

    # ── Database check with latency ──
    try:
        from bahamut.database import async_engine
        from sqlalchemy import text
        db_start = time.monotonic()
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ms = round((time.monotonic() - db_start) * 1000, 1)
        checks["database"] = {"status": "ok", "latency_ms": db_ms}
        if db_ms > 500:
            checks["database"]["warning"] = "slow"
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        checks["database"] = {"status": "error", "error": str(e)[:100]}

    # ── Redis check with latency ──
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            redis_start = time.monotonic()
            await redis_manager.redis.ping()
            redis_ms = round((time.monotonic() - redis_start) * 1000, 1)
            checks["redis"] = {"status": "ok", "latency_ms": redis_ms}
            if redis_ms > 100:
                checks["redis"]["warning"] = "slow"
        else:
            checks["redis"] = {"status": "disconnected"}
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        checks["redis"] = {"status": "error", "error": str(e)[:100]}

    # ── Degraded subsystems with severity ──
    try:
        from bahamut.shared.degraded import get_degraded_flags
        flags = get_degraded_flags()
        degraded_count = len(flags)

        critical_subs = {"portfolio.kill_switch", "portfolio.scenario_risk", "portfolio.marginal_risk"}
        critical_degraded = [k for k in flags if k in critical_subs]
        severity = "critical" if critical_degraded else ("warning" if degraded_count > 0 else "none")

        checks["degraded_subsystems"] = {
            "count": degraded_count,
            "severity": severity,
            "critical": critical_degraded,
            "subsystems": {k: v["reason"] for k, v in flags.items()},
        }
    except Exception as e:
        checks["degraded_subsystems"] = {"count": -1, "severity": "unknown", "error": str(e)[:100]}

    # ── Schema version ──
    try:
        from bahamut.db.schema.tables import SCHEMA_VERSION
        checks["schema"] = {"version": SCHEMA_VERSION}
    except Exception:
        checks["schema"] = {"version": "unknown"}

    # ── Celery queue backlog (best-effort) ──
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            backlog = await redis_manager.redis.llen("celery")
            checks["celery_queue"] = {"backlog": backlog or 0}
    except Exception:
        checks["celery_queue"] = {"backlog": "unavailable"}

    # ── Overall status ──
    db_ok = checks.get("database", {}).get("status") == "ok"
    redis_ok = checks.get("redis", {}).get("status") == "ok"
    degraded_severity = checks.get("degraded_subsystems", {}).get("severity", "none")

    if not db_ok or degraded_severity == "critical":
        overall = "critical"
    elif not redis_ok or degraded_severity == "warning":
        overall = "degraded"
    else:
        overall = "healthy"

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    return {
        "status": overall,
        "checks": checks,
        "response_time_ms": elapsed_ms,
    }
