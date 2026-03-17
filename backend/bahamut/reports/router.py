"""Report generation API routes."""
import json
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user
from bahamut.shared.redis_client import redis_manager
import structlog

logger = structlog.get_logger()
router = APIRouter()


@router.get("/daily-brief")
async def daily_brief(user=Depends(get_current_user)):
    """Get the AI-generated daily market brief. Cached for 1 hour."""
    # Check cache first
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:daily_brief")
        if cached:
            return json.loads(cached)

    # Generate fresh brief
    from bahamut.reports.daily_brief import generate_daily_brief
    brief = await generate_daily_brief()

    # Cache for 1 hour
    if redis_manager.redis:
        try:
            await redis_manager.redis.set("bahamut:daily_brief", json.dumps(brief, default=str), ex=3600)
        except Exception:
            pass

    return brief


@router.post("/daily-brief/refresh")
async def refresh_brief(user=Depends(get_current_user)):
    """Force regenerate the daily brief."""
    if redis_manager.redis:
        await redis_manager.redis.delete("bahamut:daily_brief")

    from bahamut.reports.daily_brief import generate_daily_brief
    brief = await generate_daily_brief()

    if redis_manager.redis:
        try:
            await redis_manager.redis.set("bahamut:daily_brief", json.dumps(brief, default=str), ex=3600)
        except Exception:
            pass

    return brief


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "reports-svc"}
