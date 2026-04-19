"""Daily report of safe_execute counters + general failure visibility."""
import os
from datetime import datetime, timezone
import structlog
from celery import shared_task

logger = structlog.get_logger()


def _r():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True, socket_connect_timeout=1,
        )
    except Exception:
        return None


def get_daily_safe_report() -> dict:
    """Return summary of safe_execute failures in last 24 hours."""
    r = _r()
    if not r:
        return {"error": "redis_unavailable"}
    try:
        keys = list(r.scan_iter(match="bahamut:counters:safe_*_failures"))
        counts = {}
        for k in keys:
            cat = k.replace("bahamut:counters:safe_", "").replace("_failures", "")
            counts[cat] = int(r.get(k) or 0)
        sorted_counts = dict(sorted(counts.items(), key=lambda x: -x[1]))
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_categories": len(counts),
            "total_failures_sum": sum(counts.values()),
            "top_10": dict(list(sorted_counts.items())[:10]),
            "all": sorted_counts,
        }
    except Exception as e:
        return {"error": str(e)[:100]}


@shared_task(name="bahamut.monitoring.safe_report.send_daily_report")
def send_daily_report():
    """Celery task: generate and send daily failure report via Telegram."""
    try:
        report = get_daily_safe_report()
        from bahamut.monitoring.telegram import send_alert
        top = report.get("top_10", {})
        lines = ["📊 Daily safe_execute failure report"]
        lines.append(f"Total categories: {report.get('total_categories', 0)}")
        lines.append(f"Total failures: {report.get('total_failures_sum', 0)}")
        if top:
            lines.append("Top 10:")
            for cat, cnt in top.items():
                lines.append(f"  {cat}: {cnt}")
        else:
            lines.append("No failures recorded — all clear ✓")
        send_alert("\n".join(lines))
        logger.info("daily_safe_report_sent",
                     categories=report.get("total_categories", 0),
                     failures=report.get("total_failures_sum", 0))
    except Exception as e:
        logger.error("daily_safe_report_failed", error=str(e)[:100])
