"""
Bahamut.AI — Centralized Database Access Layer

All raw SQL should flow through these helpers to ensure:
  - Connections are always properly opened/closed
  - Errors are logged consistently
  - No connection leaks under load

Usage:
    from bahamut.db.query import run_query, run_transaction

    # Read:
    rows = run_query("SELECT * FROM calibration_runs WHERE id = :id", {"id": 1})

    # Write (auto-commit):
    run_transaction(
        "INSERT INTO calibration_runs (cadence, status) VALUES (:c, :s)",
        {"c": "daily", "s": "completed"}
    )

    # Multi-statement transaction:
    def do_stuff(conn):
        conn.execute(text("INSERT INTO ..."), {...})
        conn.execute(text("UPDATE ..."), {...})
    run_in_transaction(do_stuff)
"""
import time
import structlog
from contextlib import contextmanager
from sqlalchemy import text

logger = structlog.get_logger()


def _get_sync_engine():
    """Lazy import to avoid circular dependency at module load time."""
    from bahamut.database import sync_engine
    return sync_engine


@contextmanager
def get_connection():
    """Context manager that guarantees connection cleanup.

    Usage:
        with get_connection() as conn:
            result = conn.execute(text("SELECT 1"))
    """
    engine = _get_sync_engine()
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


def run_query(sql: str, params: dict | None = None) -> list[dict]:
    """Execute a read query and return results as list of dicts.

    Connection is guaranteed to close even on error.
    """
    start = time.monotonic()
    try:
        with get_connection() as conn:
            result = conn.execute(text(sql), params or {})
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        elapsed = round((time.monotonic() - start) * 1000, 1)
        if elapsed > 500:
            logger.warning("slow_query", sql=sql[:100], elapsed_ms=elapsed)
        return rows
    except Exception as e:
        logger.error("query_failed", sql=sql[:100], error=str(e))
        raise


def run_query_one(sql: str, params: dict | None = None) -> dict | None:
    """Execute a read query and return first row or None."""
    rows = run_query(sql, params)
    return rows[0] if rows else None


def run_transaction(sql: str, params: dict | None = None) -> None:
    """Execute a single write statement with auto-commit.

    Connection is guaranteed to close even on error.
    """
    try:
        with get_connection() as conn:
            conn.execute(text(sql), params or {})
            conn.commit()
    except Exception as e:
        logger.error("transaction_failed", sql=sql[:100], error=str(e))
        raise


def run_in_transaction(fn) -> None:
    """Execute a multi-statement function inside a transaction.

    The function receives a connection. Commits on success, rolls back on error.

    Usage:
        def do_stuff(conn):
            conn.execute(text("INSERT ..."), {...})
            conn.execute(text("UPDATE ..."), {...})
        run_in_transaction(do_stuff)
    """
    engine = _get_sync_engine()
    conn = engine.connect()
    try:
        fn(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("multi_transaction_failed", error=str(e))
        raise
    finally:
        conn.close()


def ensure_table(sql: str) -> None:
    """Execute a CREATE TABLE IF NOT EXISTS statement.

    Used during schema initialization only.
    """
    try:
        with get_connection() as conn:
            conn.execute(text(sql))
            conn.commit()
    except Exception as e:
        logger.error("ensure_table_failed", sql=sql[:80], error=str(e))
        raise


def check_db_health() -> dict:
    """Quick DB health check with latency measurement."""
    start = time.monotonic()
    try:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "error", "latency_ms": elapsed_ms, "error": str(e)[:100]}
