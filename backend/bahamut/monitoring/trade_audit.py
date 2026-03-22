"""
Bahamut Trade Lifecycle Audit Logger

Records major trade lifecycle events in the admin_audit_log table:
  - test_trade.opened
  - test_trade.closed
  - signal.generated
  - order.created
  - position.opened
  - position.closed
  - kill_switch.activated
  - kill_switch.resumed
  - data.fallback

Reuses the existing admin_audit_log table (config_key = event type).
"""
import structlog

logger = structlog.get_logger()


def log_trade_event(event_type: str, details: str, actor: str = "system", metadata: str = ""):
    """
    Record a trade lifecycle event in the audit log.

    event_type: e.g. "test_trade.opened", "position.closed"
    details: human-readable description
    actor: who triggered it (system, operator, strategy name)
    metadata: JSON string of additional data
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO admin_audit_log (config_key, old_value, new_value, changed_by, action)
                VALUES (:k, :o, :n, :b, :a)
            """), {
                "k": f"event:{event_type}",
                "o": metadata or "",
                "n": details,
                "b": actor,
                "a": event_type,
            })
            conn.commit()
        logger.info("trade_event_logged", event_type=event_type, details=details[:80])
    except Exception as e:
        # Non-fatal — don't break trade flow for audit failures
        logger.debug("trade_event_log_failed", event_type=event_type, error=str(e))
