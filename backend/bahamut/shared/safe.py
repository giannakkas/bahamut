"""
Structured error handling for optional-but-tracked operations.

Replaces `try: ... except Exception: pass` with categorized,
counted, conditionally-alerting handlers.

Categories (standard):
  telegram_*        — Telegram sends
  ws_publish_*      — WebSocket publishes
  cache_invalidate  — risk engine cache, router cache
  redis_counter     — counter increments
  rejection_tracker — rejection tracker writes
  order_manager_*   — OrderManager state writes
  broker_poll       — position/order status polls
"""
import os
import structlog
from typing import Callable, Any

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


def _increment_counter(key: str) -> None:
    r = _r()
    if not r:
        return
    try:
        r.incr(key)
        r.expire(key, 86400 * 7)  # 7 day retention
    except Exception:
        pass


def safe_execute(
    func: Callable,
    *args,
    category: str = "unknown",
    critical: bool = False,
    alert_on_failure: bool = False,
    log_level: str = "warning",
    default: Any = None,
    **kwargs,
) -> Any:
    """Execute func with structured error handling.

    category: short identifier for grouping failures
    critical: if True, re-raise the exception (for must-succeed ops)
    alert_on_failure: send Telegram alert on failure
    log_level: warning|error|info|debug (default: warning)
    default: value to return on failure if not critical

    Returns func's result on success, or `default` on handled failure.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        err_str = str(e)[:200]
        log_fn = getattr(logger, log_level, logger.warning)
        log_fn(f"safe_execute_{category}_failed", error=err_str)
        _increment_counter(f"bahamut:counters:safe_{category}_failures")

        if alert_on_failure:
            try:
                from bahamut.monitoring.telegram import send_alert
                send_alert(f"⚠️ {category}: {err_str[:150]}")
            except Exception:
                pass

        if critical:
            raise

        return default


def safe_call(category: str, critical: bool = False,
              alert: bool = False, default: Any = None):
    """Decorator form of safe_execute for one-shot wrapping."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            return safe_execute(func, *args, category=category,
                                critical=critical, alert_on_failure=alert,
                                default=default, **kwargs)
        return wrapper
    return decorator
