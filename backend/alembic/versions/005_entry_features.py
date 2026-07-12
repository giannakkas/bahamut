"""005 — entry_features on positions + trades (ML meta-labeling foundation)

Persists the entry-time feature vector (indicators, readiness, macro state,
allocation tier) on every position, copied to the trade at close. This is the
training data for the meta-labeling win-probability model: validation on the
854 historical trades showed AUC ~0.52 (coin flip) because rich entry features
were never stored and 79% of labels were aging-bug timeouts. Post-fix trades
with real features are the trainable dataset.

Revision ID: 005_entry_features
Revises: 004_last_bar_time
Create Date: 2026-07-12
"""
from typing import Sequence, Union
from alembic import op

revision: str = '005_entry_features'
down_revision: Union[str, None] = '004_last_bar_time'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS entry_features TEXT DEFAULT ''")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS entry_features TEXT DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE training_positions DROP COLUMN IF EXISTS entry_features")
    op.execute("ALTER TABLE training_trades DROP COLUMN IF EXISTS entry_features")
