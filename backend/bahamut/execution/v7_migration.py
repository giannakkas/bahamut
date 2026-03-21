"""
Bahamut v7 — Database migration for trading operations.

Tables:
  strategy_sleeves — per-strategy capital allocation and tracking
  v7_orders — order lifecycle
  v7_trades — closed trade records
  v7_portfolio_snapshots — periodic equity snapshots

Run: python -m bahamut.execution.v7_migration
"""
from bahamut.database import sync_engine
from sqlalchemy import text
import structlog

logger = structlog.get_logger()

MIGRATION_SQL = """
-- Strategy sleeves
CREATE TABLE IF NOT EXISTS strategy_sleeves (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50) UNIQUE NOT NULL,
    allocation_weight FLOAT DEFAULT 0.5,
    allocated_capital FLOAT DEFAULT 50000,
    current_equity FLOAT DEFAULT 50000,
    realized_pnl FLOAT DEFAULT 0,
    unrealized_pnl FLOAT DEFAULT 0,
    peak_equity FLOAT DEFAULT 50000,
    drawdown FLOAT DEFAULT 0,
    trade_count INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Orders
CREATE TABLE IF NOT EXISTS v7_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(20) UNIQUE NOT NULL,
    strategy_name VARCHAR(50) NOT NULL,
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    signal_time TIMESTAMPTZ,
    fill_time TIMESTAMPTZ,
    entry_price FLOAT DEFAULT 0,
    stop_price FLOAT DEFAULT 0,
    tp_price FLOAT DEFAULT 0,
    size FLOAT DEFAULT 0,
    risk_amount FLOAT DEFAULT 0,
    sl_pct FLOAT DEFAULT 0,
    tp_pct FLOAT DEFAULT 0,
    max_hold_bars INTEGER DEFAULT 30,
    signal_id VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades (closed positions)
CREATE TABLE IF NOT EXISTS v7_trades (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(20) UNIQUE NOT NULL,
    order_id VARCHAR(20) NOT NULL,
    strategy_name VARCHAR(50) NOT NULL,
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT NOT NULL,
    stop_price FLOAT DEFAULT 0,
    tp_price FLOAT DEFAULT 0,
    size FLOAT DEFAULT 0,
    risk_amount FLOAT DEFAULT 0,
    pnl FLOAT DEFAULT 0,
    pnl_pct FLOAT DEFAULT 0,
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    exit_reason VARCHAR(30),
    bars_held INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Portfolio snapshots
CREATE TABLE IF NOT EXISTS v7_portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_equity FLOAT NOT NULL,
    total_realized_pnl FLOAT DEFAULT 0,
    total_unrealized_pnl FLOAT DEFAULT 0,
    total_open_risk FLOAT DEFAULT 0,
    drawdown FLOAT DEFAULT 0,
    sleeve_data JSONB DEFAULT '{}'::jsonb
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_v7_orders_strategy ON v7_orders(strategy_name);
CREATE INDEX IF NOT EXISTS idx_v7_orders_status ON v7_orders(status);
CREATE INDEX IF NOT EXISTS idx_v7_trades_strategy ON v7_trades(strategy_name);
CREATE INDEX IF NOT EXISTS idx_v7_trades_exit_time ON v7_trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_v7_snapshots_time ON v7_portfolio_snapshots(timestamp);

-- Seed default sleeves
INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity)
VALUES ('v5_base', 0.5, 50000, 50000, 50000)
ON CONFLICT (strategy_name) DO NOTHING;

INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity)
VALUES ('v5_tuned', 0.5, 50000, 50000, 50000)
ON CONFLICT (strategy_name) DO NOTHING;
"""


def run_migration():
    """Execute v7 migration."""
    try:
        with sync_engine.connect() as conn:
            for statement in MIGRATION_SQL.split(";"):
                stmt = statement.strip()
                if stmt and not stmt.startswith("--"):
                    conn.execute(text(stmt))
            conn.commit()
        logger.info("v7_migration_complete")
        print("v7 migration completed successfully")
    except Exception as e:
        logger.error("v7_migration_failed", error=str(e))
        print(f"v7 migration failed: {e}")
        raise


if __name__ == "__main__":
    run_migration()
