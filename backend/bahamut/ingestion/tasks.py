from bahamut.celery_app import celery_app
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.ingestion.tasks.ingest_ohlcv")
def ingest_ohlcv():
    logger.info("ingest_ohlcv", status="stub - connect real data source")

@celery_app.task(name="bahamut.ingestion.tasks.ingest_volatility")
def ingest_volatility():
    logger.info("ingest_volatility", status="stub")

@celery_app.task(name="bahamut.ingestion.tasks.ingest_news")
def ingest_news():
    logger.info("ingest_news", status="stub")
