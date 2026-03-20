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
    """Approve a pending APPROVAL trade — fetches price and executes immediately."""
    if user.role not in ("trader", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        from bahamut.db.query import run_query_one
        import json

        # Get latest consensus decision for this asset
        decision = run_query_one("""
            SELECT cycle_id, asset, direction, final_score, decision, execution_mode,
                   agreement_pct, regime, trading_profile, risk_flags, disagreement_metrics,
                   agent_contributions
            FROM consensus_decisions
            WHERE asset = :a ORDER BY created_at DESC LIMIT 1
        """, {"a": asset})

        if not decision:
            return {"status": "error", "message": f"No decision found for {asset}"}

        # Fetch current price
        try:
            from bahamut.ingestion.market_data import get_current_prices
            import asyncio
            prices = await get_current_prices()
            entry_price = prices.get(asset, 0)
        except Exception:
            entry_price = 0

        if entry_price <= 0:
            return {"status": "error", "message": f"Could not fetch price for {asset}"}

        # Extract parameters
        direction = decision.get("direction", "LONG")
        score = float(decision.get("final_score", 0))
        label = decision.get("decision", "SIGNAL")
        regime = decision.get("regime", "RISK_ON")
        profile = decision.get("trading_profile", "BALANCED")
        cycle_id = decision.get("cycle_id")
        risk_flags = decision.get("risk_flags") or []
        if isinstance(risk_flags, str):
            risk_flags = json.loads(risk_flags)

        dm = decision.get("disagreement_metrics") or {}
        if isinstance(dm, str):
            dm = json.loads(dm)

        agents = decision.get("agent_contributions") or {}
        if isinstance(agents, str):
            agents = json.loads(agents)

        # Estimate ATR as 1% of price (safe fallback)
        atr = entry_price * 0.01

        # Execute via sync executor
        from bahamut.paper_trading.sync_executor import process_signal_sync
        result = process_signal_sync(
            asset=asset, direction=direction,
            consensus_score=score, signal_label=label,
            entry_price=entry_price, atr=atr,
            agent_votes=agents, cycle_id=cycle_id,
            execution_gate="CLEAR", disagreement_index=dm.get("disagreement_index", 0),
            risk_flags=risk_flags, risk_can_trade=True,
            regime=regime, trading_profile=profile,
        )
        return {"status": "approved", "asset": asset, "price": entry_price, "result": result}
    except Exception as e:
        import traceback
        logger.error("approve_failed", asset=asset, error=str(e), tb=traceback.format_exc())
        return {"status": "error", "message": str(e)[:200]}


@router.post("/approve-all")
async def approve_all_trades(user=Depends(get_current_user)):
    """Approve all pending APPROVAL trades."""
    if user.role not in ("trader", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    from bahamut.db.query import run_query
    pending = run_query("""
        SELECT DISTINCT ON (asset) asset FROM consensus_decisions
        WHERE execution_mode = 'APPROVAL' AND created_at > NOW() - INTERVAL '4 hours'
    """)
    results = []
    for row in pending:
        asset = row.get("asset", "")
        try:
            # Call ourselves for each asset
            r = await approve_trade(asset, user)
            results.append(r)
        except Exception as e:
            results.append({"asset": asset, "status": "error", "error": str(e)[:100]})
    return {"status": "ok", "count": len(results), "results": results}
