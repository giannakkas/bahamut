"""004 — last_bar_time on training_positions (bar-time aging)

bars_held now increments only when the candle timestamp changes (bar-time
aging) instead of once per 10-minute cycle. last_bar_time persists the last
counted candle so aging survives Redis flushes / restarts (DB is canonical).

Revision ID: 004_last_bar_time
Revises: 003_bracket_and_funding
Create Date: 2026-07-12
"""
from typing import Sequence, Union
from alembic import op

revision: str = '004_last_bar_time'
down_revision: Union[str, None] = '003_bracket_and_funding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS last_bar_time VARCHAR(40) DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE training_positions DROP COLUMN IF EXISTS last_bar_time")
