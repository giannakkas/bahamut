"""Ingestion tasks including breaking news monitor."""
import asyncio
import json
from bahamut.celery_app import celery_app
from bahamut.agents.tasks import run_single_cycle, _cache_to_redis
import structlog

logger = structlog.get_logger()


@celery_app.task(name="bahamut.ingestion.tasks.ingest_ohlcv")
def ingest_ohlcv():
    logger.info("ingest_ohlcv", status="handled_by_market_data_service")


@celery_app.task(name="bahamut.ingestion.tasks.ingest_volatility")
def ingest_volatility():
    logger.info("ingest_volatility", status="stub")


@celery_app.task(name="bahamut.ingestion.tasks.ingest_news")
def ingest_news():
    logger.info("ingest_news", status="handled_by_breaking_news_monitor")


@celery_app.task(name="bahamut.ingestion.tasks.monitor_breaking_news")
def monitor_breaking_news():
    """
    Runs every 2 minutes. Checks for breaking news that could impact prices.
    If high-impact news detected, immediately triggers emergency signal cycles
    for affected assets instead of waiting for the 15-minute schedule.
    """
    loop = asyncio.new_event_loop()
    try:
        from bahamut.ingestion.breaking_news import check_breaking_news
        alerts = loop.run_until_complete(check_breaking_news())

        if not alerts:
            return

        logger.warning("breaking_news_alerts", count=len(alerts))

        # Store alerts in Redis for frontend display
        try:
            import redis
            from bahamut.config import get_settings
            r = redis.from_url(get_settings().redis_url)
            existing = r.get("bahamut:breaking_alerts")
            existing_list = json.loads(existing) if existing else []
            existing_list = alerts + existing_list[:20]  # Keep last 20
            r.set("bahamut:breaking_alerts", json.dumps(existing_list, default=str), ex=3600)
            r.close()
        except Exception as e:
            logger.warning("alert_cache_failed", error=str(e))

        # Trigger emergency cycles for affected assets
        triggered = set()
        for alert in alerts:
            for asset in alert.get("affected_assets", []):
                if asset not in triggered:
                    logger.warning("emergency_cycle_triggered",
                                   asset=asset,
                                   headline=alert["headline"][:80],
                                   score=alert["impact_score"],
                                   emergency=alert["is_emergency"])

                    # Determine asset class
                    asset_class = "fx"
                    if asset in ["XAUUSD"]:
                        asset_class = "commodities"
                    elif asset in ["BTCUSD", "ETHUSD"]:
                        asset_class = "crypto"
                    elif asset in ["AAPL", "TSLA", "NVDA", "META"]:
                        asset_class = "indices"

                    # Fire the cycle async via Celery
                    run_single_cycle.delay(asset, asset_class, "4H", "BALANCED")
                    triggered.add(asset)

        logger.warning("emergency_cycles_dispatched", assets=list(triggered))

    except Exception as e:
        logger.error("breaking_news_monitor_failed", error=str(e))
    finally:
        loop.close()
