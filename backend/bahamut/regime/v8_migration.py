"""
Bahamut v8 — Database migration for regime-aware portfolio.

Run: python -m bahamut.regime.v8_migration
"""
from bahamut.database import sync_engine
from sqlalchemy import text
import structlog

logger = structlog.get_logger()

V8_SQL = """
-- Regime history table
CREATE TABLE IF NOT EXISTS v8_regime_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    asset VARCHAR(20) NOT NULL DEFAULT 'BTCUSD',
    regime VARCHAR(20) NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    reason TEXT DEFAULT '',
    features JSONB DEFAULT '{}'::jsonb,
    active_strategies TEXT[] DEFAULT '{}',
    portfolio_mode VARCHAR(30) DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_v8_regime_time ON v8_regime_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_v8_regime_regime ON v8_regime_history(regime);

-- Add regime column to portfolio snapshots (if not exists)
DO $$ BEGIN
    ALTER TABLE v7_portfolio_snapshots ADD COLUMN regime VARCHAR(20) DEFAULT 'RANGE';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE v7_portfolio_snapshots ADD COLUMN portfolio_mode VARCHAR(30) DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Add regime column to trades
DO $$ BEGIN
    ALTER TABLE v7_trades ADD COLUMN regime VARCHAR(20) DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Seed v8 sleeves
INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity, enabled)
VALUES ('v8_range', 0.0, 0, 0, 0, FALSE)
ON CONFLICT (strategy_name) DO NOTHING;

INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity, enabled)
VALUES ('v8_defensive', 0.0, 0, 0, 0, FALSE)
ON CONFLICT (strategy_name) DO NOTHING;
"""


def run_migration():
    try:
        with sync_engine.connect() as conn:
            for stmt in V8_SQL.split(";"):
                s = stmt.strip()
                if s and not s.startswith("--"):
                    conn.execute(text(s))
            conn.commit()
        logger.info("v8_migration_complete")
        print("v8 migration completed successfully")
    except Exception as e:
        logger.error("v8_migration_failed", error=str(e))
        print(f"v8 migration failed: {e}")
        raise


if __name__ == "__main__":
    run_migration()
