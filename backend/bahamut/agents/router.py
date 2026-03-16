"""Agent service API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bahamut.auth.router import get_current_user
from bahamut.models import User
from bahamut.agents.tasks import run_single_cycle
from bahamut.consensus.trust_store import trust_store

router = APIRouter()

class TriggerCycleRequest(BaseModel):
    asset: str
    asset_class: str = "fx"
    timeframe: str = "4H"
    trading_profile: str = "BALANCED"

@router.post("/trigger")
async def trigger_signal_cycle(req: TriggerCycleRequest, user: User = Depends(get_current_user)):
    task = run_single_cycle.delay(req.asset, req.asset_class, req.timeframe, req.trading_profile)
    return {"task_id": task.id, "status": "queued", "asset": req.asset}

@router.get("/trust-scores")
async def get_trust_scores(user: User = Depends(get_current_user)):
    return trust_store.get_all_scores()

@router.get("/trust-scores/{agent_id}")
async def get_agent_trust(agent_id: str, user: User = Depends(get_current_user)):
    scores = trust_store.get_all_scores()
    if agent_id not in scores:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return {"agent_id": agent_id, "dimensions": scores[agent_id]}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "agent-svc", "agents": ["macro_agent", "technical_agent", "risk_agent"]}
