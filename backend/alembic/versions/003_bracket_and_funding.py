"""003 — Bracket order columns + funding accrued

Adds columns for broker-side bracket orders (SL/TP placed on Binance
after fill) and funding-rate accrual for perpetual futures.

Revision ID: 003_bracket_and_funding
Revises: 002_runtime_catchup
Create Date: 2026-04-18
"""
from typing import Sequence, Union
from alembic import op

revision: str = '003_bracket_and_funding'
down_revision: Union[str, None] = '002_runtime_catchup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS bracket_sl_order_id VARCHAR(64) DEFAULT ''")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS bracket_tp_order_id VARCHAR(64) DEFAULT ''")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS funding_accrued DOUBLE PRECISION DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE training_positions DROP COLUMN IF EXISTS bracket_sl_order_id")
    op.execute("ALTER TABLE training_positions DROP COLUMN IF EXISTS bracket_tp_order_id")
    op.execute("ALTER TABLE training_positions DROP COLUMN IF EXISTS funding_accrued")
