"""Market Scanner API — surfaces top trading opportunities."""

import json
import structlog
from fastapi import APIRouter, Depends, Query
from bahamut.auth.router import get_current_user
from bahamut.shared.redis_client import redis_manager

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/scanner", tags=["Scanner"])


@router.get("/top-picks")
async def get_top_picks(user=Depends(get_current_user)):
    """Get the latest market scan results — top opportunities ranked by score."""
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:market_scan")
        if cached:
            data = json.loads(cached)
            # Also get deep analysis results
            deep = await redis_manager.redis.get("bahamut:deep_analysis")
            deep_results = json.loads(deep) if deep else []

            # Merge deep analysis into top picks
            deep_map = {r["symbol"]: r for r in deep_results}
            for pick in data.get("top_picks", []):
                deep = deep_map.get(pick["symbol"])
                if deep:
                    pick["agent_score"] = deep.get("score", 0)
                    pick["agent_direction"] = deep.get("direction")
                    pick["agent_decision"] = deep.get("decision")
                    pick["agent_agreement"] = deep.get("agreement", 0)

            return data

    return {"top_picks": [], "all_results": [], "total_scanned": 0,
            "message": "No scan results yet. Scanner runs every 30 minutes."}


@router.get("/all")
async def get_all_scanned(
    asset_class: str = Query(None, description="Filter: fx, crypto, indices, commodities"),
    min_score: int = Query(0, ge=0, le=100),
    direction: str = Query(None, description="Filter: LONG, SHORT"),
    user=Depends(get_current_user),
):
    """Get all scanned assets with optional filters."""
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:market_scan")
        if cached:
            data = json.loads(cached)
            results = data.get("all_results", [])

            if asset_class:
                results = [r for r in results if r["asset_class"] == asset_class]
            if min_score > 0:
                results = [r for r in results if r["score"] >= min_score]
            if direction:
                results = [r for r in results if r["direction"] == direction]

            return {"results": results, "count": len(results), "filters": {
                "asset_class": asset_class, "min_score": min_score, "direction": direction,
            }}

    return {"results": [], "count": 0}


@router.post("/trigger")
async def trigger_scan(user=Depends(get_current_user)):
    """Manually trigger a full market scan."""
    from bahamut.scanner.tasks import run_market_scan
    task = run_market_scan.delay()
    return {"task_id": task.id, "status": "scan_queued",
            "message": "Full scan started. ~57 assets, takes ~2 minutes."}


@router.get("/deep-results")
async def get_deep_results(user=Depends(get_current_user)):
    """Get the latest deep 6-agent analysis results for top picks."""
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:deep_analysis")
        if cached:
            return {"results": json.loads(cached)}
    return {"results": [], "message": "No deep analysis yet. Runs after each scan."}
