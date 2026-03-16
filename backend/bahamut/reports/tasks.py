from bahamut.celery_app import celery_app
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.reports.tasks.generate_daily_brief")
def generate_daily_brief():
    logger.info("generate_daily_brief", status="stub - needs Anthropic API")
