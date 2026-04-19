"""
Bahamut Celery Configuration

LIVE trading: routes to Binance Futures Demo + Alpaca Paper via
exchange APIs. Handles 50 assets with full execution gauntlet.
"""
from celery import Celery
from celery.schedules import crontab
from bahamut.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bahamut",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "bahamut.trading.orchestrator",
        "bahamut.monitoring.safe_report",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        "bahamut.execution.*": {"queue": "critical"},
        "bahamut.trading.*": {"queue": "critical"},
    },
    beat_schedule={
        "trading-cycle": {
            "task": "bahamut.trading.orchestrator.run_trading_cycle",
            "schedule": 600.0,  # Every 10 min — batched to respect API rate limits
        },
        "daily-safe-report": {
            "task": "bahamut.monitoring.safe_report.send_daily_report",
            "schedule": crontab(hour=8, minute=0),  # 8am UTC
        },
    },
)
