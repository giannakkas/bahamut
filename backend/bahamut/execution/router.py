"""Execution service API routes."""
from fastapi import APIRouter, Depends, HTTPException
from bahamut.auth.router import get_current_user

router = APIRouter()

@router.post("/kill-switch")
async def kill_switch(user=Depends(get_current_user)):
    if user.role not in ("trader", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # In production: close all positions, cancel orders, disable auto-trade
    return {"status": "kill_switch_activated", "positions_closed": 0, "orders_cancelled": 0}

@router.get("/status")
async def execution_status(user=Depends(get_current_user)):
    return {"open_orders": 0, "pending_fills": 0, "broker_status": "healthy"}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "execution-svc"}
