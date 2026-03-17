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
    assets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "AAPL", "TSLA", "NVDA", "META"]
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
        data_source = "live"
    elif oanda.configured:
        data_source = "live"

    return {
        "status": "healthy",
        "service": "agent-svc",
        "agents": ["macro_agent", "technical_agent", "risk_agent",
                    "volatility_agent", "sentiment_agent", "liquidity_agent"],
        "agent_count": 6,
        "data_source": data_source,
        "live": td_health,
        "live": oanda_health,
    }


@router.get("/candles/{asset}")
async def get_candles(asset: str, timeframe: str = "4H", count: int = 100,
                      user: User = Depends(get_current_user)):
    """Get OHLCV candles for chart display."""
    from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol, to_twelve_interval
    from bahamut.ingestion.adapters.oanda import oanda, to_oanda_instrument, to_oanda_granularity

    candles = []
    source = "demo"

    if twelve_data.configured:
        candles = await twelve_data.get_candles(to_twelve_symbol(asset), to_twelve_interval(timeframe), count)
        source = "live"
    elif oanda.configured:
        candles = await oanda.get_candles(to_oanda_instrument(asset), to_oanda_granularity(timeframe), count)
        source = "live"

    if not candles:
        # Generate demo candles
        import random
        base = {"EURUSD": 1.15, "GBPUSD": 1.27, "USDJPY": 149.8, "XAUUSD": 2645}.get(asset, 1.15)
        step = base * 0.001
        candles = []
        for i in range(count):
            o = base + random.uniform(-step * 5, step * 5)
            c = o + random.uniform(-step * 3, step * 3)
            h = max(o, c) + random.uniform(0, step * 2)
            l = min(o, c) - random.uniform(0, step * 2)
            candles.append({"time": f"2026-03-{17 - count + i:02d}T{(i % 24):02d}:00:00",
                            "open": round(o, 5), "high": round(h, 5),
                            "low": round(l, 5), "close": round(c, 5),
                            "volume": random.randint(1000, 50000)})
            base = c
        source = "demo"

    return {"candles": candles, "source": source, "asset": asset, "timeframe": timeframe}


@router.get("/macro-overview")
async def macro_overview(user: User = Depends(get_current_user)):
    """Cross-asset overview with latest prices and indicators."""
    from bahamut.ingestion.market_data import market_data

    assets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "AAPL", "TSLA", "NVDA", "META"]
    overview = {}

    for asset in assets:
        try:
            features = await market_data.get_features_for_asset(asset, "4H")
            ind = features.get("indicators", {})
            overview[asset] = {
                "price": ind.get("close", 0),
                "rsi": round(ind.get("rsi_14", 50), 1),
                "macd": round(ind.get("macd_histogram", 0), 6),
                "adx": round(ind.get("adx_14", 20), 1),
                "atr": round(ind.get("atr_14", 0), 6),
                "ema_20": round(ind.get("ema_20", 0), 6),
                "ema_50": round(ind.get("ema_50", 0), 6),
                "ema_200": round(ind.get("ema_200", 0), 6),
                "stoch_k": round(ind.get("stoch_k", 50), 1),
                "bb_upper": round(ind.get("bollinger_upper", 0), 6),
                "bb_lower": round(ind.get("bollinger_lower", 0), 6),
                "vol_20": round(ind.get("realized_vol_20", 0), 4),
                "trend": "BULLISH" if ind.get("close", 0) > ind.get("ema_50", 0) > ind.get("ema_200", 0) else
                         "BEARISH" if ind.get("close", 0) < ind.get("ema_50", 0) < ind.get("ema_200", 0) else "MIXED",
                "momentum": "STRONG" if ind.get("adx_14", 0) > 25 else "WEAK",
                "source": features.get("source", "demo"),
            }
        except Exception as e:
            overview[asset] = {"error": str(e)}

    return overview


@router.get("/history")
async def get_cycle_history(
    asset: str = None,
    limit: int = 50,
    user=Depends(get_current_user),
):
    """Get historical signal cycle results from database."""
    from sqlalchemy import text
    from bahamut.database import async_engine
    from sqlalchemy.ext.asyncio import AsyncSession

    query = """
        SELECT cd.id, cd.cycle_id, cd.asset, cd.direction, cd.final_score,
               cd.decision, cd.agreement_pct, cd.regime, cd.trading_profile,
               cd.execution_mode, cd.blocked, cd.explanation,
               cd.agent_contributions, cd.risk_flags, cd.created_at
        FROM consensus_decisions cd
    """
    params = {"limit": limit}

    if asset:
        query += " WHERE cd.asset = :asset"
        params["asset"] = asset

    query += " ORDER BY cd.created_at DESC LIMIT :limit"

    try:
        async with AsyncSession(async_engine) as session:
            result = await session.execute(text(query), params)
            rows = result.mappings().all()

        return [{
            "id": str(r["id"]),
            "cycle_id": str(r["cycle_id"]),
            "asset": r["asset"],
            "direction": r["direction"],
            "score": float(r["final_score"]) if r["final_score"] else 0,
            "decision": r["decision"],
            "agreement": float(r["agreement_pct"]) if r["agreement_pct"] else 0,
            "regime": r["regime"],
            "profile": r["trading_profile"],
            "mode": r["execution_mode"],
            "blocked": r["blocked"],
            "explanation": r["explanation"],
            "risk_flags": r["risk_flags"] if isinstance(r["risk_flags"], list) else [],
            "created_at": str(r["created_at"]) if r["created_at"] else "",
        } for r in rows]
    except Exception as e:
        logger.error("history_query_failed", error=str(e))
        return []


@router.get("/breaking-alerts")
async def get_breaking_alerts(user=Depends(get_current_user)):
    """Get recent breaking news alerts that triggered emergency cycles."""
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:breaking_alerts")
        if cached:
            return {"alerts": json.loads(cached)}
    return {"alerts": []}
