"""Learning service API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user
from bahamut.consensus.trust_store import trust_store

router = APIRouter()

@router.get("/trust-scores")
async def get_all_trust(user=Depends(get_current_user)):
    return trust_store.get_all_scores()

@router.get("/fitness")
async def strategy_fitness(user=Depends(get_current_user)):
    return {
        "sharpe_30d": 1.24,
        "win_rate_30d": 0.673,
        "regime_stability": "stable",
        "model_freshness": "current",
        "backtest_divergence": 0.8,
    }

@router.post("/emergency-recalibrate")
async def emergency_recalibrate(user=Depends(get_current_user)):
    trust_store.apply_daily_decay(decay_rate=0.05)
    return {"status": "emergency_recalibration_applied", "decay_rate": 0.05}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "learning-svc"}
