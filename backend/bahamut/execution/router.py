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


@router.post("/approve/{asset}")
async def approve_trade(asset: str, user=Depends(get_current_user)):
    """Approve a pending APPROVAL trade for execution."""
    if user.role not in ("trader", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        from bahamut.paper_trading.sync_executor import SyncPaperExecutor
        executor = SyncPaperExecutor()
        
        # Get latest cycle for this asset
        from bahamut.db.query import run_query_one
        cycle = run_query_one("""
            SELECT cycle_id, asset, direction, final_score, execution_mode
            FROM consensus_decisions
            WHERE asset = :a ORDER BY created_at DESC LIMIT 1
        """, {"a": asset})
        
        if not cycle:
            return {"status": "error", "message": f"No cycle found for {asset}"}
        
        if cycle.get("execution_mode") != "APPROVAL":
            return {"status": "skipped", "message": f"{asset} is not pending approval"}
        
        # Force execute by triggering the sync executor
        result = executor.execute_cycle_sync(
            asset=asset,
            asset_class="fx" if "USD" in asset or "EUR" in asset or "GBP" in asset or "JPY" in asset else "indices",
            timeframe="4H",
            trading_profile="BALANCED",
        )
        return {"status": "approved", "asset": asset, "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


@router.post("/approve-all")
async def approve_all_trades(user=Depends(get_current_user)):
    """Approve all pending APPROVAL trades."""
    if user.role not in ("trader", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        from bahamut.db.query import run_query
        pending = run_query("""
            SELECT DISTINCT asset FROM consensus_decisions
            WHERE execution_mode = 'APPROVAL'
            AND created_at > NOW() - INTERVAL '2 hours'
            ORDER BY asset
        """)
        results = []
        for row in pending:
            asset = row.get("asset", "")
            try:
                from bahamut.paper_trading.sync_executor import SyncPaperExecutor
                executor = SyncPaperExecutor()
                r = executor.execute_cycle_sync(
                    asset=asset,
                    asset_class="fx" if any(c in asset for c in ["USD","EUR","GBP","JPY"]) else "indices",
                    timeframe="4H",
                    trading_profile="BALANCED",
                )
                results.append({"asset": asset, "status": "approved", "result": str(r)[:100]})
            except Exception as e:
                results.append({"asset": asset, "status": "error", "error": str(e)[:100]})
        return {"status": "ok", "approved_count": len(results), "results": results}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
