"""Initial schema - all tables

Revision ID: 001_initial
Revises:
Create Date: 2026-03-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, BYTEA

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Use Alembic's connection to create tables from SQLAlchemy metadata
    from bahamut.database import Base
    from bahamut.models import *  # noqa - register all models
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from bahamut.database import Base
    from bahamut.models import *  # noqa
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
