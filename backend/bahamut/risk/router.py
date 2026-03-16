"""Risk control API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user

router = APIRouter()

@router.get("/dashboard")
async def risk_dashboard(user=Depends(get_current_user)):
    return {
        "drawdown": {"daily": 0.012, "weekly": 0.008, "total": 0.042},
        "limits": {"daily": 0.030, "weekly": 0.060, "total": 0.150},
        "exposure": {"net": 0.07, "long": 0.07, "short": 0.0},
        "circuit_breakers": [
            {"name": "Drawdown Lock", "active": False},
            {"name": "Volatility Freeze", "active": False},
            {"name": "Event Freeze", "active": True, "reason": "US CPI in 4h"},
            {"name": "Systemic Risk", "active": False},
            {"name": "News Shock", "active": False},
            {"name": "Broker Status", "active": False, "status": "healthy"},
        ],
        "correlation": {"max": 0.35, "threshold": 0.70},
    }

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "risk-svc"}
