"""Celery tasks for agent orchestration with live market data."""
import asyncio
import json
from bahamut.celery_app import celery_app
from bahamut.agents.orchestrator import orchestrator
from bahamut.agents.persistence import save_cycle_to_db
import structlog

logger = structlog.get_logger()

ACTIVE_ASSETS = [
    {"symbol": "EURUSD", "asset_class": "fx"},
    {"symbol": "GBPUSD", "asset_class": "fx"},
    {"symbol": "USDJPY", "asset_class": "fx"},
    {"symbol": "XAUUSD", "asset_class": "commodities"},
]


def _cache_to_redis(asset: str, result: dict):
    try:
        import redis
        from bahamut.config import get_settings
        r = redis.from_url(get_settings().redis_url)
        r.set(f"bahamut:latest_cycle:{asset}", json.dumps(result, default=str), ex=1800)
        r.close()
    except Exception as e:
        logger.warning("redis_cache_failed", error=str(e))


@celery_app.task(name="bahamut.agents.tasks.run_all_signal_cycles")
def run_all_signal_cycles():
    logger.info("signal_cycles_batch_started", assets=len(ACTIVE_ASSETS))
    loop = asyncio.new_event_loop()

    for asset_info in ACTIVE_ASSETS:
        try:
            result = loop.run_until_complete(
                orchestrator.run_cycle(
                    asset=asset_info["symbol"],
                    asset_class=asset_info["asset_class"],
                    timeframe="4H",
                    trading_profile="BALANCED",
                )
            )
            d = result.get("decision", {})
            logger.info("cycle_result", asset=asset_info["symbol"],
                        direction=d.get("direction"), score=d.get("final_score"),
                        decision=d.get("decision"), source=result.get("data_source"))

            _cache_to_redis(asset_info["symbol"], result)
            save_cycle_to_db(result)

        except Exception as e:
            logger.exception("cycle_failed", asset=asset_info["symbol"], error=str(e))

    loop.close()
    logger.info("signal_cycles_batch_completed")


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
        return result
    except Exception as e:
        logger.exception("single_cycle_failed", error=str(e))
        return {"error": str(e)}
    finally:
        loop.close()
