"""Learning Celery Tasks — real calibration replacing stubs."""
from bahamut.celery_app import celery_app
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.learning.tasks.daily_trust_decay")
def daily_trust_decay():
    from bahamut.consensus.trust_store import trust_store
    trust_store.apply_daily_decay()
    logger.info("daily_trust_decay_applied")

@celery_app.task(name="bahamut.learning.tasks.daily_threshold_adjustment")
def daily_threshold_adjustment():
    from bahamut.learning.calibration import run_daily_calibration
    r = run_daily_calibration()
    logger.info("daily_calibration", trades=r.trades_analyzed)
    return {"status": "completed", "trades": r.trades_analyzed}

@celery_app.task(name="bahamut.learning.tasks.weekly_calibration")
def weekly_calibration():
    from bahamut.learning.calibration import run_weekly_calibration
    r = run_weekly_calibration()
    logger.info("weekly_calibration", trades=r.trades_analyzed)
    return {"status": "completed", "trades": r.trades_analyzed}

@celery_app.task(name="bahamut.learning.tasks.monthly_calibration")
def monthly_calibration():
    from bahamut.learning.calibration import run_weekly_calibration
    r = run_weekly_calibration()
    return {"status": "completed"}

@celery_app.task(name="bahamut.learning.tasks.trade_triggered_calibration")
def trade_triggered_calibration():
    from bahamut.learning.calibration import run_trade_triggered_calibration
    r = run_trade_triggered_calibration(threshold=20)
    return {"triggered": r is not None}
