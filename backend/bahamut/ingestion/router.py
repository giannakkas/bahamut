"""Market data API routes."""
from fastapi import APIRouter, Depends, Query
import structlog
from bahamut.auth.router import get_current_user
from bahamut.models import User
from bahamut.ingestion.market_data import market_data
from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol, to_twelve_interval
from bahamut.ingestion.adapters.oanda import oanda, to_oanda_instrument, to_oanda_granularity

logger = structlog.get_logger()
router = APIRouter()


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str, timeframe: str = Query("4H"), count: int = Query(200, ge=10, le=500),
    user: User = Depends(get_current_user),
):
    if twelve_data.configured:
        candles = await twelve_data.get_candles(to_twelve_symbol(symbol), to_twelve_interval(timeframe), count)
        if candles:
            return {"symbol": symbol, "timeframe": timeframe, "source": "live", "count": len(candles), "candles": candles}
    if oanda.configured:
        candles = await oanda.get_candles(to_oanda_instrument(symbol), to_oanda_granularity(timeframe), count)
        if candles:
            return {"symbol": symbol, "timeframe": timeframe, "source": "live", "count": len(candles), "candles": candles}
    return {"symbol": symbol, "source": "none", "count": 0, "candles": []}


@router.get("/price/{symbol}")
async def get_price(symbol: str, user: User = Depends(get_current_user)):
    if twelve_data.configured:
        price = await twelve_data.get_latest_price(to_twelve_symbol(symbol))
        if price:
            return price
    return {"instrument": symbol, "mid": 0}


@router.get("/calendar")
async def get_economic_calendar(days: int = 7, user: User = Depends(get_current_user)):
    from bahamut.ingestion.adapters.news import econ_calendar
    events = await econ_calendar.get_upcoming_events(days)
    return {"events": events, "count": len(events), "source": "finnhub" if events else "none"}


@router.get("/news")
async def get_market_news(
    query: str = Query("general", description="Category: general, forex, crypto, merger"),
    count: int = 15,
    user: User = Depends(get_current_user),
):
    from bahamut.ingestion.adapters.news import news_adapter
    articles = await news_adapter.get_headlines(query, count)
    return {"articles": articles, "count": len(articles)}


@router.get("/news/{symbol}")
async def get_asset_news(symbol: str, count: int = 5, user: User = Depends(get_current_user)):
    from bahamut.ingestion.adapters.news import news_adapter
    articles = await news_adapter.get_asset_news(symbol, count)
    return {"symbol": symbol, "articles": articles, "count": len(articles)}


@router.get("/calendar-debug")
async def debug_calendar(user: User = Depends(get_current_user)):
    """Debug: test Finnhub calendar directly."""
    import httpx, os
    from datetime import datetime, timezone, timedelta
    from bahamut.config import get_settings
    s = get_settings()
    key = s.finnhub_key

    if not key:
        return {"error": "FINNHUB_KEY not set", "env_check": bool(os.environ.get("FINNHUB_KEY"))}

    start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://finnhub.io/api/v1/calendar/economic", params={
                "from": start, "to": end, "token": key,
            })
            return {
                "status": resp.status_code,
                "key_length": len(key),
                "url": str(resp.url),
                "data_keys": list(resp.json().keys()) if resp.status_code == 200 else None,
                "sample": resp.json() if resp.status_code == 200 else resp.text[:500],
            }
    except Exception as e:
        return {"error": str(e)}
