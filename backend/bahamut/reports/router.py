"""Report generation API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user

router = APIRouter()

@router.get("/daily-brief")
async def daily_brief(user=Depends(get_current_user)):
    return {
        "date": "2026-03-16",
        "regime": "RISK_ON",
        "summary": "Markets are in a risk-on regime with moderate confidence. EUR showing strength against USD on diverging rate expectations. VIX stable at 18.5. Key event: US CPI release in 4 hours. Agent council consensus leans bullish on EURUSD (0.74 score, 78% agreement). Risk parameters within bounds. Recommend: monitor CPI release before new entries.",
        "signals_generated": 2,
        "trades_executed": 3,
        "risk_events": 0,
    }

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "reports-svc"}
