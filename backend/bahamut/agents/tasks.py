"""Celery tasks for agent orchestration with live market data."""
import asyncio
import json
from datetime import datetime, timezone
from bahamut.celery_app import celery_app
from bahamut.agents.orchestrator import orchestrator
from bahamut.agents.persistence import save_cycle_to_db, save_decision_trace
import structlog

logger = structlog.get_logger()

# Assets monitored - split by market type for scheduling
FX_ASSETS = [
    {"symbol": "EURUSD", "asset_class": "fx"},
    {"symbol": "GBPUSD", "asset_class": "fx"},
    {"symbol": "USDJPY", "asset_class": "fx"},
    {"symbol": "EURJPY", "asset_class": "fx"},
    {"symbol": "GBPJPY", "asset_class": "fx"},
    {"symbol": "AUDUSD", "asset_class": "fx"},
    {"symbol": "USDCAD", "asset_class": "fx"},
    {"symbol": "EURGBP", "asset_class": "fx"},
    {"symbol": "USDCHF", "asset_class": "fx"},
    {"symbol": "NZDUSD", "asset_class": "fx"},
]

COMMODITY_ASSETS = [
    {"symbol": "XAUUSD", "asset_class": "commodities"},
    {"symbol": "XAGUSD", "asset_class": "commodities"},
    {"symbol": "WTIUSD", "asset_class": "commodities"},
    {"symbol": "NATGASUSD", "asset_class": "commodities"},
]

CRYPTO_ASSETS = [
    {"symbol": "BTCUSD", "asset_class": "crypto"},
    {"symbol": "ETHUSD", "asset_class": "crypto"},
    {"symbol": "SOLUSD", "asset_class": "crypto"},
    {"symbol": "BNBUSD", "asset_class": "crypto"},
    {"symbol": "XRPUSD", "asset_class": "crypto"},
    {"symbol": "ADAUSD", "asset_class": "crypto"},
    {"symbol": "DOGEUSD", "asset_class": "crypto"},
    {"symbol": "LINKUSD", "asset_class": "crypto"},
    {"symbol": "AVAXUSD", "asset_class": "crypto"},
    {"symbol": "DOTUSD", "asset_class": "crypto"},
    {"symbol": "TONUSD", "asset_class": "crypto"},
    {"symbol": "SHIBUSD", "asset_class": "crypto"},
    {"symbol": "NEARUSD", "asset_class": "crypto"},
    {"symbol": "SUIUSD", "asset_class": "crypto"},
    {"symbol": "LTCUSD", "asset_class": "crypto"},
]

STOCK_ASSETS = [
    # Mega Cap
    {"symbol": "AAPL", "asset_class": "indices"},
    {"symbol": "MSFT", "asset_class": "indices"},
    {"symbol": "GOOGL", "asset_class": "indices"},
    {"symbol": "AMZN", "asset_class": "indices"},
    {"symbol": "NVDA", "asset_class": "indices"},
    {"symbol": "META", "asset_class": "indices"},
    {"symbol": "TSLA", "asset_class": "indices"},
    # Finance
    {"symbol": "JPM", "asset_class": "indices"},
    {"symbol": "V", "asset_class": "indices"},
    {"symbol": "MA", "asset_class": "indices"},
    {"symbol": "BAC", "asset_class": "indices"},
    {"symbol": "GS", "asset_class": "indices"},
    # Healthcare
    {"symbol": "UNH", "asset_class": "indices"},
    {"symbol": "LLY", "asset_class": "indices"},
    {"symbol": "JNJ", "asset_class": "indices"},
    {"symbol": "PFE", "asset_class": "indices"},
    {"symbol": "ABBV", "asset_class": "indices"},
    # Consumer
    {"symbol": "HD", "asset_class": "indices"},
    {"symbol": "PG", "asset_class": "indices"},
    {"symbol": "KO", "asset_class": "indices"},
    {"symbol": "COST", "asset_class": "indices"},
    {"symbol": "WMT", "asset_class": "indices"},
    {"symbol": "NKE", "asset_class": "indices"},
    # Tech / Semis
    {"symbol": "AMD", "asset_class": "indices"},
    {"symbol": "AVGO", "asset_class": "indices"},
    {"symbol": "CRM", "asset_class": "indices"},
    {"symbol": "NFLX", "asset_class": "indices"},
    {"symbol": "ADBE", "asset_class": "indices"},
    {"symbol": "MU", "asset_class": "indices"},
    {"symbol": "QCOM", "asset_class": "indices"},
    {"symbol": "ARM", "asset_class": "indices"},
    {"symbol": "PANW", "asset_class": "indices"},
    {"symbol": "CRWD", "asset_class": "indices"},
    {"symbol": "PLTR", "asset_class": "indices"},
    {"symbol": "NOW", "asset_class": "indices"},
    # Crypto-adjacent / High-vol
    {"symbol": "COIN", "asset_class": "indices"},
    {"symbol": "MSTR", "asset_class": "indices"},
    {"symbol": "SQ", "asset_class": "indices"},
    {"symbol": "SHOP", "asset_class": "indices"},
    {"symbol": "UBER", "asset_class": "indices"},
    # Energy
    {"symbol": "XOM", "asset_class": "indices"},
    {"symbol": "CVX", "asset_class": "indices"},
    # Industrial
    {"symbol": "GE", "asset_class": "indices"},
    {"symbol": "CAT", "asset_class": "indices"},
    {"symbol": "BA", "asset_class": "indices"},
    # Media
    {"symbol": "DIS", "asset_class": "indices"},
    {"symbol": "SPOT", "asset_class": "indices"},
]

ALL_ASSETS = FX_ASSETS + COMMODITY_ASSETS + CRYPTO_ASSETS + STOCK_ASSETS


def _cache_to_redis(asset: str, result: dict):
    try:
        import redis
        from bahamut.config import get_settings
        r = redis.from_url(get_settings().redis_url)
        r.set(f"bahamut:latest_cycle:{asset}", json.dumps(result, default=str), ex=1800)
        r.close()
    except Exception as e:
        logger.warning("redis_cache_failed", error=str(e))


def _run_assets(assets: list, timeframe: str = "4H"):
    loop = asyncio.new_event_loop()
    for asset_info in assets:
        try:
            result = loop.run_until_complete(
                orchestrator.run_cycle(
                    asset=asset_info["symbol"],
                    asset_class=asset_info["asset_class"],
                    timeframe=timeframe,
                    trading_profile="BALANCED",
                )
            )
            d = result.get("decision", {})
            logger.info("cycle_result", asset=asset_info["symbol"],
                        direction=d.get("direction"), score=d.get("final_score"),
                        source=result.get("data_source"))

            _cache_to_redis(asset_info["symbol"], result)
            save_cycle_to_db(result)
            save_decision_trace(result)

        except Exception as e:
            logger.exception("cycle_failed", asset=asset_info["symbol"], error=str(e))
    loop.close()


@celery_app.task(name="bahamut.agents.tasks.run_all_signal_cycles")
def run_all_signal_cycles():
    """Runs FX + Commodity + Crypto every 15 min."""
    logger.info("signal_cycles_fx_crypto_started")
    _run_assets(FX_ASSETS + COMMODITY_ASSETS + CRYPTO_ASSETS)
    logger.info("signal_cycles_fx_crypto_completed")


@celery_app.task(name="bahamut.agents.tasks.run_stock_cycles")
def run_stock_cycles():
    """Runs stocks every 30 min during market hours."""
    now = datetime.now(timezone.utc)
    # US market hours: 13:30-20:00 UTC (9:30am-4pm ET)
    if now.weekday() < 5 and 13 <= now.hour < 20:
        logger.info("stock_cycles_started")
        _run_assets(STOCK_ASSETS, timeframe="1D")
        logger.info("stock_cycles_completed")
    else:
        logger.info("stock_cycles_skipped", reason="outside_market_hours")


@celery_app.task(name="bahamut.agents.tasks.run_single_cycle")
def run_single_cycle(asset: str, asset_class: str = "fx",
                     timeframe: str = "4H", trading_profile: str = "BALANCED"):
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            orchestrator.run_cycle(
                asset=asset, asset_class=asset_class,
                timeframe=timeframe, trading_profile=trading_profile,
                triggered_by="MANUAL",
            )
        )
        _cache_to_redis(asset, result)
        save_cycle_to_db(result)
        save_decision_trace(result)
        return result
    except Exception as e:
        logger.exception("single_cycle_failed", error=str(e))
        return {"error": str(e)}
    finally:
        loop.close()
