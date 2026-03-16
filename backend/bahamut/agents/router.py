from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import json
import structlog

from bahamut.auth.router import get_current_user
from bahamut.models import User
from bahamut.agents.tasks import run_single_cycle
from bahamut.consensus.trust_store import trust_store
from bahamut.shared.redis_client import redis_manager

logger = structlog.get_logger()
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


@router.get("/latest-cycle/{asset}")
async def get_latest_cycle(asset: str, user: User = Depends(get_current_user)):
    if redis_manager.redis:
        cached = await redis_manager.redis.get(f"bahamut:latest_cycle:{asset}")
        if cached:
            return json.loads(cached)
    return {"message": f"No recent cycle for {asset}. Trigger one first."}


@router.get("/latest-cycles")
async def get_all_latest_cycles(user: User = Depends(get_current_user)):
    assets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
    results = {}
    if redis_manager.redis:
        for asset in assets:
            cached = await redis_manager.redis.get(f"bahamut:latest_cycle:{asset}")
            if cached:
                results[asset] = json.loads(cached)
    return results


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
    from bahamut.ingestion.adapters.oanda import oanda
    from bahamut.ingestion.adapters.twelvedata import twelve_data

    td_health = await twelve_data.health_check()
    oanda_health = await oanda.health_check()

    data_source = "none"
    if twelve_data.configured:
        data_source = "twelvedata"
    elif oanda.configured:
        data_source = "oanda"

    return {
        "status": "healthy",
        "service": "agent-svc",
        "agents": ["macro_agent", "technical_agent", "risk_agent",
                    "volatility_agent", "sentiment_agent", "liquidity_agent"],
        "agent_count": 6,
        "data_source": data_source,
        "twelvedata": td_health,
        "oanda": oanda_health,
    }
