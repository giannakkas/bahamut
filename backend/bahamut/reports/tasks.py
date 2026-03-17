"""Report generation tasks."""
import asyncio
import json
from bahamut.celery_app import celery_app
import structlog

logger = structlog.get_logger()


@celery_app.task(name="bahamut.reports.tasks.generate_daily_brief")
def generate_daily_brief():
    """Generate and cache the daily market brief using Gemini."""
    loop = asyncio.new_event_loop()
    try:
        from bahamut.reports.daily_brief import generate_daily_brief as gen
        brief = loop.run_until_complete(gen())

        # Cache in Redis
        try:
            import redis
            from bahamut.config import get_settings
            r = redis.from_url(get_settings().redis_url)
            r.set("bahamut:daily_brief", json.dumps(brief, default=str), ex=3600)
            r.close()
        except Exception as e:
            logger.warning("brief_cache_failed", error=str(e))

        logger.info("daily_brief_generated", model=brief.get("model"),
                     signals=brief.get("signals_analyzed"),
                     regime=brief.get("regime"))
        return brief
    except Exception as e:
        logger.error("daily_brief_failed", error=str(e))
        return {"error": str(e)}
    finally:
        loop.close()
