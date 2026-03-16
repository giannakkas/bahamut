"""Initial schema - all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, BYTEA, ARRAY, INET

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # All tables are auto-created by SQLAlchemy metadata.create_all
    # via the models imported in env.py. This migration serves as
    # the baseline marker.
    from bahamut.database import Base, sync_engine
    Base.metadata.create_all(bind=sync_engine)


def downgrade() -> None:
    from bahamut.database import Base, sync_engine
    Base.metadata.drop_all(bind=sync_engine)
