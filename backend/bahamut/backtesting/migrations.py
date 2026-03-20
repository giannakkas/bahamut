"""
Database migrations for backtesting and risk counterfactual tracking.
Run via: python -m bahamut.backtesting.migrations
"""

MIGRATION_SQL = """
-- Risk counterfactual tracking table
CREATE TABLE IF NOT EXISTS risk_counterfactuals (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    stop_loss DOUBLE PRECISION NOT NULL,
    take_profit DOUBLE PRECISION NOT NULL,
    block_reason TEXT,
    cycle_id VARCHAR(64),
    outcome VARCHAR(10),  -- WIN, LOSS, or NULL (pending)
    exit_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_counterfactuals_pending
    ON risk_counterfactuals (outcome) WHERE outcome IS NULL;

CREATE INDEX IF NOT EXISTS idx_counterfactuals_asset
    ON risk_counterfactuals (asset, created_at);

-- Backtest results storage
CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL UNIQUE,
    asset VARCHAR(20) NOT NULL,
    asset_class VARCHAR(20),
    timeframe VARCHAR(10),
    candle_count INTEGER,
    config JSONB,
    metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

def run_migration():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    from bahamut.database import sync_engine
    from sqlalchemy import text

    with sync_engine.connect() as conn:
        for statement in MIGRATION_SQL.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
        conn.commit()
    print("✅ Migrations applied")

if __name__ == "__main__":
    run_migration()
