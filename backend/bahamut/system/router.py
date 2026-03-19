"""
Bahamut.AI System Health Endpoint

Lightweight health check that reports:
  - Core system status (up/degraded/down)
  - Database connectivity
  - Redis connectivity
  - Degraded subsystems from the degraded-mode tracker
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

    Returns system health summary including DB, Redis,
    and any degraded subsystems.
    """
    start = time.monotonic()
    checks = {}

    # ── Database check ──
    try:
        from bahamut.database import async_engine
        from sqlalchemy import text
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        checks["database"] = {"status": "error", "error": str(e)[:100]}

    # ── Redis check ──
    try:
        from bahamut.shared.redis_client import redis_manager
        if redis_manager.redis:
            await redis_manager.redis.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "disconnected"}
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        checks["redis"] = {"status": "error", "error": str(e)[:100]}

    # ── Degraded subsystems ──
    try:
        from bahamut.shared.degraded import get_degraded_flags
        flags = get_degraded_flags()
        checks["degraded_subsystems"] = {
            "count": len(flags),
            "subsystems": {k: v["reason"] for k, v in flags.items()},
        }
    except Exception as e:
        checks["degraded_subsystems"] = {"count": -1, "error": str(e)[:100]}

    # ── Overall status ──
    db_ok = checks.get("database", {}).get("status") == "ok"
    redis_ok = checks.get("redis", {}).get("status") == "ok"
    degraded_count = checks.get("degraded_subsystems", {}).get("count", 0)

    if not db_ok:
        overall = "critical"
    elif not redis_ok or degraded_count > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    return {
        "status": overall,
        "checks": checks,
        "response_time_ms": elapsed_ms,
    }
