"""
Bahamut Celery Configuration

OPERATIONAL MODE: Only the v7/v8/v9 trading engine runs.
Legacy tasks (scanner, agents, learning, old paper trading) are DISABLED.
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
        # ── OPERATIONAL (active) ──
        "bahamut.execution.v7_orchestrator",
        "bahamut.training.orchestrator",

        # ── LEGACY (loaded but not scheduled) ──
        # Kept importable for manual research use, but no beat tasks.
        # "bahamut.ingestion.tasks",
        # "bahamut.features.tasks",
        # "bahamut.agents.tasks",
        # "bahamut.learning.tasks",
        # "bahamut.reports.tasks",
        # "bahamut.paper_trading.tasks",
        # "bahamut.scanner.tasks",
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
    },
    beat_schedule={
        # ══════════════════════════════════════════════
        # OPERATIONAL ENGINE — the only active schedule
        # ══════════════════════════════════════════════
        "v7-trading-cycle": {
            "task": "bahamut.execution.v7_orchestrator.run_v7_cycle",
            "schedule": 120.0,  # Every 2 min — only acts on new 4H bars
        },

        # ══════════════════════════════════════════════
        # TRAINING UNIVERSE — paper trading 50 assets
        # Feeds the learning engine. Isolated from production.
        # ══════════════════════════════════════════════
        "training-cycle": {
            "task": "bahamut.training.orchestrator.run_training_cycle",
            "schedule": 600.0,  # Every 10 min — batched to respect API rate limits
        },

        # ══════════════════════════════════════════════
        # LEGACY — ALL DISABLED
        # These were the old multi-agent scanner system.
        # Kept commented for reference only.
        # ══════════════════════════════════════════════
        # "ingest-ohlcv": { ... },
        # "ingest-volatility": { ... },
        # "ingest-news": { ... },
        # "compute-features": { ... },
        # "detect-regime": { ... },
        # "monitor-breaking-news": { ... },
        # "run-stock-cycles": { ... },
        # "run-signal-cycles": { ... },
        # "run-market-scan": { ... },
        # "daily-trust-decay": { ... },
        # "daily-threshold-adjust": { ... },
        # "weekly-calibration": { ... },
        # "monthly-calibration": { ... },
        # "daily-brief": { ... },
        # "check-paper-positions": { ... },
        # "paper-trading-daily-report": { ... },
        # "market-scanner": { ... },
        # "trade-triggered-calibration": { ... },
    },
)
