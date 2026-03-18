"""
SQLAlchemy database layer for Bahamut TICC.

Uses SQLite by default, swappable to PostgreSQL via DATABASE_URL env var.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import get_settings

logger = logging.getLogger("bahamut.db")

Base = declarative_base()

# ─── ORM Models ───────────────────────────────────────────────────


class ConfigRow(Base):
    __tablename__ = "config"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=False)  # JSON-serialized
    type = Column(String(16), nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=False, default="")
    default_value = Column(Text, nullable=False)
    min_val = Column(Float, nullable=True)
    max_val = Column(Float, nullable=True)
    options = Column(Text, nullable=True)  # comma-separated


class OverrideRow(Base):
    __tablename__ = "overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), nullable=False)
    value = Column(Text, nullable=False)
    ttl = Column(Integer, nullable=False)
    created = Column(String(64), nullable=False)
    expires = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False, default="")


class AuditRow(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    old_value = Column(Text, nullable=False)
    new_value = Column(Text, nullable=False)
    source = Column(String(16), nullable=False, default="user")
    user = Column(String(64), nullable=False, default="system")


class AlertRow(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(String(64), nullable=False)
    dismissed = Column(Boolean, nullable=False, default=False)


class StateRow(Base):
    """Key-value store for singleton state like kill_switch."""

    __tablename__ = "state"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)


# ─── Engine / Session ─────────────────────────────────────────────

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            echo=False,
        )
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine())
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    factory = _get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Init / Seed ──────────────────────────────────────────────────

def init_db() -> None:
    """Create tables and seed default data if empty."""
    # Ensure SQLite directory exists
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        import os
        # sqlite:////app/data/bahamut.db → /app/data/bahamut.db
        # sqlite:///./bahamut.db → ./bahamut.db
        db_path = settings.database_url.split("///")[-1]
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

    with get_session() as session:
        count = session.query(ConfigRow).count()
        if count == 0:
            _seed_defaults(session)
            logger.info("Seeded default data")
        else:
            logger.info(f"Database already has {count} config keys, skipping seed")


def _seed_defaults(session: Session) -> None:
    """Seed initial config, alerts, audit entries, and state."""
    from services.seed_data import SEED_CONFIG, SEED_AUDIT, SEED_ALERTS

    # Config
    for key, meta in SEED_CONFIG.items():
        session.add(ConfigRow(
            key=key,
            value=str(meta["value"]),
            type=meta["type"],
            category=meta["category"],
            description=meta["description"],
            default_value=str(meta["default"]),
            min_val=meta.get("min"),
            max_val=meta.get("max"),
            options=",".join(meta["options"]) if meta.get("options") else None,
        ))

    # Audit
    for entry in SEED_AUDIT:
        session.add(AuditRow(**entry))

    # Alerts
    for alert in SEED_ALERTS:
        session.add(AlertRow(**alert))

    # State
    session.add(StateRow(key="kill_switch_active", value="false"))
    session.add(StateRow(key="kill_switch_reason", value=""))
    session.add(StateRow(key="kill_switch_last_triggered", value="2026-03-17T14:32:00Z"))

    session.flush()
