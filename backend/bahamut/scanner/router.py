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
    data = None

    # Try Redis first
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:market_scan")
        if cached:
            data = json.loads(cached)

    # Fall back to PostgreSQL
    if not data:
        from bahamut.agents.persistence import get_latest_scan
        data = get_latest_scan()

    if data:
        # Merge deep analysis results
        if redis_manager.redis:
            deep = await redis_manager.redis.get("bahamut:deep_analysis")
            deep_results = json.loads(deep) if deep else []
            deep_map = {r["symbol"]: r for r in deep_results}
            for pick in data.get("top_picks", []):
                d = deep_map.get(pick["symbol"])
                if d:
                    pick["agent_score"] = d.get("score", 0)
                    pick["agent_direction"] = d.get("direction")
                    pick["agent_decision"] = d.get("decision")
                    pick["agent_agreement"] = d.get("agreement", 0)
        return data

    return {"top_picks": [], "all_results": [], "total_scanned": 0,
            "message": "No scan results yet. Click Scan Now or wait for next auto-scan (every 30 min)."}


@router.get("/all")
async def get_all_scanned(
    asset_class: str = Query(None, description="Filter: fx, crypto, indices, commodities"),
    min_score: int = Query(0, ge=0, le=100),
    direction: str = Query(None, description="Filter: LONG, SHORT"),
    user=Depends(get_current_user),
):
    """Get all scanned assets with optional filters."""
    data = None
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:market_scan")
        if cached:
            data = json.loads(cached)
    if not data:
        from bahamut.agents.persistence import get_latest_scan
        data = get_latest_scan()

    if data:
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


@router.get("/test")
async def test_scan(user=Depends(get_current_user)):
    """Quick test — scan 3 assets synchronously to verify scanner works."""
    from bahamut.scanner.scanner import scan_single_asset
    results = []
    errors = []
    for symbol in ["BTCUSD", "AAPL", "EURUSD"]:
        try:
            r = await scan_single_asset(symbol, "4h")
            if r:
                results.append(r)
            else:
                errors.append({"symbol": symbol, "error": "returned None"})
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
    return {"results": results, "errors": errors}


@router.get("/whales/{symbol}")
async def get_whale_data(symbol: str, user=Depends(get_current_user)):
    """Get detailed whale analysis for a specific asset."""
    from bahamut.whales.tracker import get_whale_score
    from bahamut.scanner.scanner import SYMBOL_CLASS

    asset_class = SYMBOL_CLASS.get(symbol, "indices")

    # Fetch candles for volume analysis
    from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol
    candles = await twelve_data.get_candles(to_twelve_symbol(symbol), "4h", 30)

    result = await get_whale_score(symbol, asset_class, candles)
    result["symbol"] = symbol
    result["asset_class"] = asset_class
    return result


@router.get("/whales")
async def get_all_whale_activity(user=Depends(get_current_user)):
    """Get whale activity summary across all scanned assets."""
    # Try Redis first, fall back to DB
    data = None
    if redis_manager.redis:
        cached = await redis_manager.redis.get("bahamut:market_scan")
        if cached:
            data = json.loads(cached)
    if not data:
        from bahamut.agents.persistence import get_latest_scan
        data = get_latest_scan()

    if data:
        results = data.get("all_results", [])
        whale_active = [r for r in results if r.get("whale_score", 0) != 0]
        whale_active.sort(key=lambda x: abs(x.get("whale_score", 0)), reverse=True)
        return {"active": whale_active, "count": len(whale_active), "total_scanned": len(results)}
    return {"active": [], "count": 0}


@router.get("/history")
async def get_scan_history(limit: int = 10, user=Depends(get_current_user)):
    """Get past scan summaries (without full results to keep response small)."""
    from sqlalchemy import text
    from bahamut.database import sync_engine
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, scanned_at, total_scanned, elapsed_sec, timeframe
                FROM scan_history ORDER BY scanned_at DESC LIMIT :limit
            """), {"limit": limit})
            rows = result.mappings().all()
            return {"scans": [dict(r) for r in rows]}
    except Exception:
        return {"scans": []}
