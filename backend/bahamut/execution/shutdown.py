"""
Bahamut.AI — Graceful Shutdown Handler

On SIGTERM (Railway deploy, scale-down):
  1. Sets system to degraded state (blocks new trades)
  2. Persists all in-memory state to Redis
  3. Marks in-flight operations for reconciliation
  4. Logs shutdown reason

On startup:
  1. Checks for unclean shutdown marker
  2. Triggers reconciliation if needed
  3. Restores state from Redis/DB

Usage:
  # At app startup:
  from bahamut.execution.shutdown import register_shutdown_handlers
  register_shutdown_handlers()

  # In middleware/health:
  from bahamut.execution.shutdown import is_shutting_down
  if is_shutting_down():
      return {"status": "shutting_down"}
"""
import os
import signal
import time
import structlog

logger = structlog.get_logger()

_shutting_down = False
_shutdown_at = 0.0


def is_shutting_down() -> bool:
    """Check if the system is in shutdown mode. Use this to block new trades.
    Checks process-local flag first, then Redis marker for cross-worker visibility."""
    if _shutting_down:
        return True
    try:
        import redis, os
        r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
        if r.get("bahamut:shutdown_in_progress"):
            return True
    except Exception:
        pass
    return False


def _shutdown_handler(signum, frame):
    """Handle SIGTERM/SIGINT gracefully."""
    global _shutting_down, _shutdown_at
    if _shutting_down:
        return  # Already handling

    _shutting_down = True
    _shutdown_at = time.time()
    sig_name = signal.Signals(signum).name if signum else "UNKNOWN"

    logger.warning("GRACEFUL_SHUTDOWN_INITIATED",
                   signal=sig_name,
                   timestamp=time.time())

    # 1. Mark system as degraded in Redis (blocks new trades across workers)
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        r.setex("bahamut:shutdown_in_progress", 120, json.dumps({
            "signal": sig_name,
            "timestamp": time.time(),
            "worker_id": os.environ.get("HOSTNAME", "unknown"),
        }))
        logger.info("shutdown_marker_set_in_redis")
    except Exception as e:
        logger.error("shutdown_redis_marker_failed", error=str(e)[:100])

    # 2. Mark any in-flight orders as needing reconciliation
    try:
        from bahamut.execution.order_manager import OrderManager, OrderState
        mgr = OrderManager()
        in_flight = mgr.get_intents_needing_reconciliation()
        for intent in in_flight:
            try:
                mgr.transition(intent["id"], OrderState.RECONCILE_REQUIRED,
                               {"reason": f"graceful_shutdown_{sig_name}"})
            except Exception:
                pass
        if in_flight:
            logger.warning("shutdown_marked_inflight_for_reconciliation",
                           count=len(in_flight))
    except Exception as e:
        logger.error("shutdown_inflight_marking_failed", error=str(e)[:100])

    # 3. Persist training positions to Redis (already happens on save,
    #    but force a full write to ensure nothing is lost)
    try:
        from bahamut.training.engine import _load_positions, _save_position
        positions = _load_positions()
        for pos in positions:
            try:
                _save_position(pos)
            except Exception:
                pass
        logger.info("shutdown_positions_persisted", count=len(positions))
    except Exception as e:
        logger.error("shutdown_position_persist_failed", error=str(e)[:100])

    logger.warning("GRACEFUL_SHUTDOWN_COMPLETE",
                   duration_ms=round((time.time() - _shutdown_at) * 1000))


def register_shutdown_handlers():
    """Register SIGTERM and SIGINT handlers. Call once at app startup."""
    try:
        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)
        logger.info("shutdown_handlers_registered")
    except Exception as e:
        # In some contexts (e.g., non-main thread), signal registration fails
        logger.warning("shutdown_handlers_not_registered",
                       error=str(e)[:100],
                       note="May be running in non-main thread")


def check_unclean_shutdown() -> bool:
    """Check if a previous instance shut down uncleanly.
    Call at startup. Returns True if reconciliation is needed."""
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        raw = r.get("bahamut:shutdown_in_progress")
        if raw:
            data = json.loads(raw)
            logger.warning("unclean_shutdown_detected",
                           previous_shutdown=data)
            # Clear the marker
            r.delete("bahamut:shutdown_in_progress")
            return True
    except Exception:
        pass
    return False


def startup_reconciliation():
    """Run after app startup if unclean shutdown was detected."""
    if not check_unclean_shutdown():
        return

    logger.warning("startup_reconciliation_triggered",
                   reason="previous unclean shutdown")

    try:
        from bahamut.execution.reconciliation import reconcile_all
        result = reconcile_all()
        logger.info("startup_reconciliation_complete",
                    summary=result.get("summary", {}))
    except Exception as e:
        logger.error("startup_reconciliation_failed", error=str(e)[:200])
