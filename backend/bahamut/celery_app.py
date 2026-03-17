from celery import Celery
from celery.schedules import crontab
from bahamut.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bahamut",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "bahamut.ingestion.tasks",
        "bahamut.features.tasks",
        "bahamut.agents.tasks",
        "bahamut.learning.tasks",
        "bahamut.reports.tasks",
        "bahamut.paper_trading.tasks",
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
        "bahamut.ingestion.*": {"queue": "ingestion"},
        "bahamut.agents.*": {"queue": "agents"},
        "bahamut.learning.*": {"queue": "learning"},
        "bahamut.reports.*": {"queue": "reports"},
        "bahamut.risk.*": {"queue": "critical"},
        "bahamut.execution.*": {"queue": "critical"},
        "paper_trading.*": {"queue": "agents"},
    },
    beat_schedule={
        "ingest-ohlcv": {
            "task": "bahamut.ingestion.tasks.ingest_ohlcv",
            "schedule": 300.0,  # Every 5 min (was 60s)
        },
        "ingest-volatility": {
            "task": "bahamut.ingestion.tasks.ingest_volatility",
            "schedule": 600.0,  # Every 10 min (was 60s)
        },
        "ingest-news": {
            "task": "bahamut.ingestion.tasks.ingest_news",
            "schedule": 600.0,  # Every 10 min (was 5 min)
        },
        "compute-features": {
            "task": "bahamut.features.tasks.compute_features",
            "schedule": 300.0,  # Every 5 min (was 60s)
        },
        "detect-regime": {
            "task": "bahamut.features.tasks.detect_regime",
            "schedule": 600.0,  # Every 10 min (was 5 min)
        },
        "monitor-breaking-news": {
            "task": "bahamut.ingestion.tasks.monitor_breaking_news",
            "schedule": 300.0,  # Every 5 min (was 2 min)
        },
        "run-stock-cycles": {
            "task": "bahamut.agents.tasks.run_stock_cycles",
            "schedule": 3600.0,  # Every 60 min (was 30 min)
        },
        "run-signal-cycles": {
            "task": "bahamut.agents.tasks.run_all_signal_cycles",
            "schedule": 1800.0,  # Every 30 min (was 15 min) — saves ~50% credits
        },
        "daily-trust-decay": {
            "task": "bahamut.learning.tasks.daily_trust_decay",
            "schedule": crontab(hour=0, minute=15),
        },
        "daily-threshold-adjust": {
            "task": "bahamut.learning.tasks.daily_threshold_adjustment",
            "schedule": crontab(hour=0, minute=30),
        },
        "weekly-calibration": {
            "task": "bahamut.learning.tasks.weekly_calibration",
            "schedule": crontab(day_of_week=0, hour=20, minute=0),
        },
        "monthly-calibration": {
            "task": "bahamut.learning.tasks.monthly_calibration",
            "schedule": crontab(day_of_month=1, hour=2, minute=0),
        },
        "daily-brief": {
            "task": "bahamut.reports.tasks.generate_daily_brief",
            "schedule": crontab(hour=6, minute=0),
        },
        "check-paper-positions": {
            "task": "paper_trading.check_positions",
            "schedule": 300.0,  # Every 5 min (was 60s) — saves API credits
        },
        "paper-trading-daily-report": {
            "task": "paper_trading.daily_report",
            "schedule": crontab(hour=22, minute=0),
        },
    },
)
