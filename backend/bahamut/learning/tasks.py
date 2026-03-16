from bahamut.celery_app import celery_app
from bahamut.consensus.trust_store import trust_store
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.learning.tasks.daily_trust_decay")
def daily_trust_decay():
    trust_store.apply_daily_decay()
    logger.info("daily_trust_decay_applied")

@celery_app.task(name="bahamut.learning.tasks.daily_threshold_adjustment")
def daily_threshold_adjustment():
    logger.info("daily_threshold_adjustment", status="stub - needs trade history")

@celery_app.task(name="bahamut.learning.tasks.weekly_calibration")
def weekly_calibration():
    logger.info("weekly_calibration", status="stub")

@celery_app.task(name="bahamut.learning.tasks.monthly_calibration")
def monthly_calibration():
    logger.info("monthly_calibration", status="stub")
