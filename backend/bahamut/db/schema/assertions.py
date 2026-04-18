"""
Bahamut.AI — Schema Assertions

Replaces runtime CREATE TABLE / ALTER TABLE with loud assertions.
Alembic is the sole source of truth for schema changes.

Usage:
    from bahamut.db.schema.assertions import assert_table_exists, assert_column_exists

    assert_table_exists("training_trades")
    assert_column_exists("training_trades", "substrategy")
"""
import structlog

logger = structlog.get_logger()

_CHECKED: set[str] = set()


def assert_table_exists(table_name: str) -> bool:
    """Assert that a table exists in the database.
    Logs ERROR and returns False if missing. Caches positive results."""
    key = f"table:{table_name}"
    if key in _CHECKED:
        return True
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t"
            ), {"t": table_name}).fetchone()
            if row:
                _CHECKED.add(key)
                return True
            else:
                logger.error("SCHEMA_ASSERTION_FAILED",
                             table=table_name,
                             msg=f"Table '{table_name}' does not exist. "
                                 f"Run: alembic upgrade head")
                return False
    except Exception as e:
        logger.error("schema_assertion_error",
                     table=table_name, error=str(e)[:200])
        return False


def assert_column_exists(table_name: str, column_name: str) -> bool:
    """Assert that a column exists on a table.
    Logs ERROR and returns False if missing. Caches positive results."""
    key = f"col:{table_name}.{column_name}"
    if key in _CHECKED:
        return True
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "AND column_name = :c"
            ), {"t": table_name, "c": column_name}).fetchone()
            if row:
                _CHECKED.add(key)
                return True
            else:
                logger.error("SCHEMA_ASSERTION_FAILED",
                             table=table_name, column=column_name,
                             msg=f"Column '{table_name}.{column_name}' missing. "
                                 f"Run: alembic upgrade head")
                return False
    except Exception as e:
        logger.error("schema_assertion_error",
                     table=table_name, column=column_name,
                     error=str(e)[:200])
        return False


def assert_schema_ready() -> dict:
    """Check all critical tables exist. Returns {ok: bool, missing: [...]}.
    Called once at startup from init_schema()."""
    critical_tables = [
        "training_trades", "training_positions",
        "order_intents", "order_events",
        "paper_portfolios", "paper_positions",
        "admin_config", "admin_audit_log",
        "revoked_tokens",
    ]
    missing = [t for t in critical_tables if not assert_table_exists(t)]
    if missing:
        logger.error("SCHEMA_NOT_READY",
                     missing=missing,
                     msg="Critical tables missing. Run: alembic upgrade head")
    else:
        logger.info("schema_ready", tables_checked=len(critical_tables))
    return {"ok": len(missing) == 0, "missing": missing}
