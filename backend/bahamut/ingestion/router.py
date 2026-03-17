"""Market data API routes - candles, prices."""
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
    symbol: str,
    timeframe: str = Query("4H", description="1m,5m,15m,30m,1H,4H,1D,1W"),
    count: int = Query(200, ge=10, le=500),
    user: User = Depends(get_current_user),
):
    """Get OHLCV candles for charting. Returns data from live source."""
    # Try Twelve Data
    if twelve_data.configured:
        td_sym = to_twelve_symbol(symbol)
        td_int = to_twelve_interval(timeframe)
        candles = await twelve_data.get_candles(td_sym, td_int, count)
        if candles:
            return {"symbol": symbol, "timeframe": timeframe, "source": "live",
                    "count": len(candles), "candles": candles}

    # Try OANDA
    if oanda.configured:
        oa_inst = to_oanda_instrument(symbol)
        oa_gran = to_oanda_granularity(timeframe)
        candles = await oanda.get_candles(oa_inst, oa_gran, count)
        if candles:
            return {"symbol": symbol, "timeframe": timeframe, "source": "live",
                    "count": len(candles), "candles": candles}

    return {"symbol": symbol, "timeframe": timeframe, "source": "none",
            "count": 0, "candles": [], "message": "No data source configured"}


@router.get("/prices")
async def get_all_prices(user: User = Depends(get_current_user)):
    """Get latest prices for all monitored assets."""
    prices = await market_data.get_all_prices()
    return {"prices": prices}


@router.get("/price/{symbol}")
async def get_price(symbol: str, user: User = Depends(get_current_user)):
    """Get latest price for one symbol."""
    if twelve_data.configured:
        td_sym = to_twelve_symbol(symbol)
        price = await twelve_data.get_latest_price(td_sym)
        if price:
            return price

    if oanda.configured:
        oa_inst = to_oanda_instrument(symbol)
        price = await oanda.get_latest_price(oa_inst)
        if price:
            return price

    return {"instrument": symbol, "mid": 0, "message": "No data source"}


@router.get("/calendar")
async def get_economic_calendar(
    days: int = 7,
    user: User = Depends(get_current_user),
):
    """Get upcoming economic events."""
    from bahamut.ingestion.adapters.news import econ_calendar
    events = await econ_calendar.get_upcoming_events(days)
    return {"events": events, "count": len(events), "source": "twelvedata" if events else "none"}


@router.get("/news")
async def get_market_news(
    query: str = "forex market trading",
    count: int = 10,
    user: User = Depends(get_current_user),
):
    """Get financial news headlines."""
    from bahamut.ingestion.adapters.news import news_adapter
    articles = await news_adapter.get_headlines(query, count)
    return {"articles": articles, "count": len(articles)}


@router.get("/news/{symbol}")
async def get_asset_news(
    symbol: str,
    count: int = 5,
    user: User = Depends(get_current_user),
):
    """Get news for a specific asset."""
    from bahamut.ingestion.adapters.news import news_adapter
    articles = await news_adapter.get_asset_news(symbol, count)
    return {"symbol": symbol, "articles": articles, "count": len(articles)}
