import structlog
logger = structlog.get_logger()
"""Execution service — real kill switch + policy config."""
from fastapi import APIRouter, Depends, HTTPException
from bahamut.auth.router import get_current_user
from bahamut.execution.policy import PROFILE_LIMITS

router = APIRouter()

@router.post("/kill-switch")
async def kill_switch(user=Depends(get_current_user)):
    if user.role not in ("trader", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        from bahamut.paper_trading.store import close_all_positions
        closed = close_all_positions()
        return {"status": "kill_switch_activated", "positions_closed": closed}
    except Exception as e:
        return {"status": "error", "error": str(e), "positions_closed": 0}

@router.get("/status")
async def execution_status(user=Depends(get_current_user)):
    from bahamut.database import sync_engine
    from sqlalchemy import text
    try:
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FILTER (WHERE status='OPEN') as open,
                       COUNT(*) FILTER (WHERE status='OPEN' AND opened_at > NOW()-INTERVAL '1 hour') as recent
                FROM paper_positions
            """)).mappings().first()
            return {"open_positions": r["open"] if r else 0, "recent_opens_1h": r["recent"] if r else 0,
                    "execution_mode": "PAPER", "policy_active": True}
    except Exception as e:

        logger.warning("execution_silent_error", error=str(e))
        return {"open_positions": 0, "execution_mode": "PAPER", "policy_active": True}

@router.get("/policy-config")
async def get_policy_config(user=Depends(get_current_user)):
    return PROFILE_LIMITS

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "execution-svc"}
