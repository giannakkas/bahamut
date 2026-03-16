from bahamut.celery_app import celery_app
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.features.tasks.compute_features")
def compute_features():
    logger.info("compute_features", status="stub")

@celery_app.task(name="bahamut.features.tasks.detect_regime")
def detect_regime():
    logger.info("detect_regime", status="stub")
