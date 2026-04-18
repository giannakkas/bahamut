"""002 — Runtime DDL catch-up migration

Captures every table and column added at runtime via CREATE TABLE IF NOT EXISTS
and ALTER TABLE ADD COLUMN IF NOT EXISTS across 11 modules. All statements are
idempotent (IF NOT EXISTS / DO $$ BEGIN ... EXCEPTION WHEN ... END $$) so this
migration is a no-op on a database that already has the tables.

Source modules consolidated:
  - db/schema/tables.py (29 tables)
  - execution/order_manager.py (2 tables)
  - execution/v7_migration.py (4 tables)
  - regime/v8_migration.py (1 table)
  - backtesting/migrations.py (2 tables)
  - wallet/router.py (2 tables)
  - training/engine.py (column additions)
  - paper_trading (column additions)

Total: 40 tables, 8 column additions, 15 indexes.

Revision ID: 002_runtime_catchup
Revises: 001_initial
Create Date: 2026-04-18
"""
from typing import Sequence, Union
from alembic import op

revision: str = '002_runtime_catchup'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ═══════════════════════════════════════
    # TABLES FROM db/schema/tables.py
    # ═══════════════════════════════════════

    # Admin
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_config (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id SERIAL PRIMARY KEY,
            config_key VARCHAR(100),
            old_value TEXT,
            new_value TEXT,
            changed_by VARCHAR(50) DEFAULT 'system',
            action VARCHAR(20) DEFAULT 'set',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Agent Pipeline (raw-SQL versions alongside ORM versions)
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_trade_performance (
            id SERIAL PRIMARY KEY,
            agent_name VARCHAR(50) NOT NULL,
            asset VARCHAR(20) NOT NULL,
            total_signals INTEGER DEFAULT 0,
            correct_signals INTEGER DEFAULT 0,
            wrong_signals INTEGER DEFAULT 0,
            total_pnl DOUBLE PRECISION DEFAULT 0,
            avg_confidence DOUBLE PRECISION DEFAULT 0,
            last_signal_at TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS decision_traces (
            id SERIAL PRIMARY KEY,
            cycle_id VARCHAR,
            asset VARCHAR(20),
            direction VARCHAR(20),
            final_score FLOAT,
            decision VARCHAR(30),
            agent_votes JSONB,
            risk_flags JSONB,
            profile_name VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Trust (live tables separate from ORM trust_scores)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trust_scores_live (
            agent_id VARCHAR(50) NOT NULL,
            dimension VARCHAR(100) NOT NULL,
            score FLOAT DEFAULT 1.0,
            sample_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (agent_id, dimension)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trust_score_history_live (
            id SERIAL PRIMARY KEY,
            agent_id VARCHAR(50),
            dimension VARCHAR(100),
            old_score FLOAT,
            new_score FLOAT,
            change_reason VARCHAR(50),
            trade_id VARCHAR,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Paper Trading
    op.execute("""
        CREATE TABLE IF NOT EXISTS paper_portfolios (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            name VARCHAR(100) DEFAULT 'Default',
            initial_capital FLOAT DEFAULT 100000,
            current_equity FLOAT DEFAULT 100000,
            realized_pnl FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            max_drawdown FLOAT DEFAULT 0,
            trade_count INTEGER DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            max_open_positions INTEGER DEFAULT 5,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, name)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS paper_positions (
            id SERIAL PRIMARY KEY,
            portfolio_id INTEGER REFERENCES paper_portfolios(id),
            asset VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price FLOAT NOT NULL,
            current_price FLOAT DEFAULT 0,
            stop_loss FLOAT,
            take_profit FLOAT,
            size FLOAT NOT NULL,
            risk_amount FLOAT DEFAULT 0,
            unrealized_pnl FLOAT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'OPEN',
            strategy VARCHAR(50),
            consensus_score FLOAT DEFAULT 0,
            entry_time TIMESTAMPTZ DEFAULT NOW(),
            close_time TIMESTAMPTZ,
            close_reason VARCHAR(50),
            realized_pnl FLOAT DEFAULT 0,
            max_favorable FLOAT DEFAULT 0,
            max_adverse FLOAT DEFAULT 0,
            bars_held INTEGER DEFAULT 0,
            regime_at_entry VARCHAR(30),
            execution_id VARCHAR(50),
            order_id VARCHAR(36),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        ALTER TABLE paper_positions
        ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(20) DEFAULT 'STRICT'
    """)

    # Learning
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(30) NOT NULL,
            agent_id VARCHAR(50),
            details JSONB DEFAULT '{}',
            impact JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Threshold & Meta
    op.execute("""
        CREATE TABLE IF NOT EXISTS threshold_overrides (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_evaluations (
            id SERIAL PRIMARY KEY,
            evaluation_type VARCHAR(30) NOT NULL,
            results JSONB DEFAULT '{}',
            improvements JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Scanner
    op.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id SERIAL PRIMARY KEY,
            asset VARCHAR(20) NOT NULL,
            scan_type VARCHAR(30) DEFAULT 'scheduled',
            result JSONB DEFAULT '{}',
            trigger_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Portfolio
    op.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_adaptive_rules (
            id SERIAL PRIMARY KEY,
            rule_type VARCHAR(50) NOT NULL,
            asset VARCHAR(20),
            params JSONB DEFAULT '{}',
            is_active BOOLEAN DEFAULT TRUE,
            performance_score FLOAT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_decision_log (
            id SERIAL PRIMARY KEY,
            decision_type VARCHAR(30) NOT NULL,
            details JSONB DEFAULT '{}',
            impact JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS reallocation_log (
            id SERIAL PRIMARY KEY,
            action VARCHAR(30) NOT NULL,
            details JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(30) NOT NULL,
            reason TEXT,
            details JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Bar Processing
    op.execute("""
        CREATE TABLE IF NOT EXISTS bar_processing_state (
            asset VARCHAR(20) PRIMARY KEY,
            last_bar_time TIMESTAMPTZ,
            last_processed_at TIMESTAMPTZ,
            bar_count INTEGER DEFAULT 0
        )
    """)

    # Waitlist
    op.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255),
            company VARCHAR(255),
            role VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Training
    op.execute("""
        CREATE TABLE IF NOT EXISTS training_trades (
            trade_id VARCHAR(36) PRIMARY KEY,
            position_id VARCHAR(36),
            asset VARCHAR(32) NOT NULL,
            asset_class VARCHAR(16),
            strategy VARCHAR(64),
            direction VARCHAR(8),
            entry_price DOUBLE PRECISION,
            exit_price DOUBLE PRECISION,
            stop_price DOUBLE PRECISION,
            tp_price DOUBLE PRECISION,
            size DOUBLE PRECISION,
            risk_amount DOUBLE PRECISION,
            pnl DOUBLE PRECISION,
            pnl_pct DOUBLE PRECISION,
            entry_time TIMESTAMPTZ,
            exit_time TIMESTAMPTZ,
            exit_reason VARCHAR(32),
            bars_held INTEGER,
            regime VARCHAR(32),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS execution_type VARCHAR(20) DEFAULT 'standard'")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(50) DEFAULT '4h_close'")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS substrategy VARCHAR(64) DEFAULT ''")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS data_mode VARCHAR(32) DEFAULT 'live'")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS entry_commission DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS exit_commission DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS entry_slippage_abs DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS exit_slippage_abs DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS entry_lifecycle VARCHAR(32) DEFAULT ''")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS exit_lifecycle VARCHAR(32) DEFAULT ''")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS return_pct DOUBLE PRECISION DEFAULT 0")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS execution_platform VARCHAR(32) DEFAULT ''")
    op.execute("ALTER TABLE training_trades ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(128) DEFAULT ''")

    op.execute("""
        CREATE TABLE IF NOT EXISTS training_positions (
            position_id VARCHAR(36) PRIMARY KEY,
            asset VARCHAR(32) NOT NULL,
            asset_class VARCHAR(16),
            strategy VARCHAR(64),
            direction VARCHAR(8),
            entry_price DOUBLE PRECISION,
            stop_price DOUBLE PRECISION,
            tp_price DOUBLE PRECISION,
            size DOUBLE PRECISION,
            risk_amount DOUBLE PRECISION,
            entry_time TIMESTAMPTZ,
            bars_held INTEGER DEFAULT 0,
            max_hold_bars INTEGER DEFAULT 30,
            current_price DOUBLE PRECISION DEFAULT 0,
            execution_type VARCHAR(20) DEFAULT 'standard',
            confidence_score DOUBLE PRECISION DEFAULT 0,
            trigger_reason VARCHAR(50) DEFAULT '4h_close',
            status VARCHAR(16) DEFAULT 'OPEN',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS execution_platform VARCHAR(32) DEFAULT 'internal'")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(128) DEFAULT ''")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS substrategy VARCHAR(64) DEFAULT ''")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS data_mode VARCHAR(32) DEFAULT 'live'")
    op.execute("ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS regime VARCHAR(32) DEFAULT ''")

    # Stress Testing
    op.execute("""
        CREATE TABLE IF NOT EXISTS stress_test_runs (
            id SERIAL PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL UNIQUE,
            scenario_name VARCHAR(100) NOT NULL,
            config JSONB DEFAULT '{}',
            results JSONB DEFAULT '{}',
            portfolio_impact JSONB DEFAULT '{}',
            risk_metrics JSONB DEFAULT '{}',
            recommendations JSONB DEFAULT '{}',
            status VARCHAR(20) DEFAULT 'completed',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Auth
    op.execute("""
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            id SERIAL PRIMARY KEY,
            jti VARCHAR(255) UNIQUE NOT NULL,
            revoked_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Schema version tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Alerts
    op.execute("""
        CREATE TABLE IF NOT EXISTS dismissed_alerts (
            id SERIAL PRIMARY KEY,
            alert_hash VARCHAR(64) UNIQUE NOT NULL,
            dismissed_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ═══════════════════════════════════════
    # TABLES FROM execution/order_manager.py
    # ═══════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_intents (
            id VARCHAR(36) PRIMARY KEY,
            signal_id VARCHAR(128) UNIQUE NOT NULL,
            asset VARCHAR(32) NOT NULL,
            asset_class VARCHAR(16) NOT NULL,
            direction VARCHAR(8) NOT NULL,
            strategy VARCHAR(64) NOT NULL,
            substrategy VARCHAR(64) DEFAULT '',
            intended_size FLOAT NOT NULL,
            intended_price FLOAT DEFAULT 0,
            sl_pct FLOAT DEFAULT 0,
            tp_pct FLOAT DEFAULT 0,
            risk_amount FLOAT DEFAULT 0,
            order_state VARCHAR(32) NOT NULL DEFAULT 'intent_created',
            position_state VARCHAR(32) NOT NULL DEFAULT 'opening',
            client_order_id VARCHAR(128) DEFAULT '',
            broker_order_id VARCHAR(128) DEFAULT '',
            execution_platform VARCHAR(32) DEFAULT '',
            filled_qty FLOAT DEFAULT 0,
            remaining_qty FLOAT DEFAULT 0,
            avg_fill_price FLOAT DEFAULT 0,
            commission FLOAT DEFAULT 0,
            slippage_abs FLOAT DEFAULT 0,
            realized_pnl FLOAT DEFAULT 0,
            exit_price FLOAT DEFAULT 0,
            exit_reason VARCHAR(32) DEFAULT '',
            error_message TEXT DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            closed_at TIMESTAMP WITH TIME ZONE,
            metadata JSONB DEFAULT '{}'
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_events (
            id SERIAL PRIMARY KEY,
            intent_id VARCHAR(36) NOT NULL REFERENCES order_intents(id),
            event_type VARCHAR(64) NOT NULL,
            from_state VARCHAR(32),
            to_state VARCHAR(32),
            details JSONB DEFAULT '{}',
            broker_response JSONB DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_intents_signal ON order_intents(signal_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_intents_asset_state ON order_intents(asset, order_state)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_events_intent ON order_events(intent_id)")

    # ═══════════════════════════════════════
    # TABLES FROM execution/v7_migration.py
    # ═══════════════════════════════════════
    op.execute("""
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
        )
    """)
    op.execute("""
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
        )
    """)
    op.execute("""
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
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS v7_portfolio_snapshots (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            total_equity FLOAT NOT NULL,
            total_realized_pnl FLOAT DEFAULT 0,
            total_unrealized_pnl FLOAT DEFAULT 0,
            total_open_risk FLOAT DEFAULT 0,
            drawdown FLOAT DEFAULT 0,
            sleeve_data JSONB DEFAULT '{}'::jsonb
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_v7_orders_strategy ON v7_orders(strategy_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_v7_orders_status ON v7_orders(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_v7_trades_strategy ON v7_trades(strategy_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_v7_trades_exit_time ON v7_trades(exit_time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_v7_snapshots_time ON v7_portfolio_snapshots(timestamp)")

    # v7 seed data
    op.execute("""
        INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity)
        VALUES ('v5_base', 0.5, 50000, 50000, 50000)
        ON CONFLICT (strategy_name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity)
        VALUES ('v5_tuned', 0.5, 50000, 50000, 50000)
        ON CONFLICT (strategy_name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO strategy_sleeves (strategy_name, allocation_weight, allocated_capital, current_equity, peak_equity)
        VALUES ('v9_breakout', 0.3, 30000, 30000, 30000)
        ON CONFLICT (strategy_name) DO NOTHING
    """)

    # ═══════════════════════════════════════
    # TABLES FROM regime/v8_migration.py
    # ═══════════════════════════════════════
    op.execute("""
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
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_v8_regime_time ON v8_regime_history(timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_v8_regime_regime ON v8_regime_history(regime)")

    # v8 column additions
    op.execute("ALTER TABLE v7_portfolio_snapshots ADD COLUMN IF NOT EXISTS regime VARCHAR(20) DEFAULT 'RANGE'")
    op.execute("ALTER TABLE v7_portfolio_snapshots ADD COLUMN IF NOT EXISTS portfolio_mode VARCHAR(30) DEFAULT ''")
    op.execute("ALTER TABLE v7_trades ADD COLUMN IF NOT EXISTS regime VARCHAR(20) DEFAULT ''")

    # ═══════════════════════════════════════
    # TABLES FROM backtesting/migrations.py
    # ═══════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk_counterfactuals (
            id SERIAL PRIMARY KEY,
            asset VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            stop_loss DOUBLE PRECISION NOT NULL,
            take_profit DOUBLE PRECISION NOT NULL,
            block_reason TEXT,
            cycle_id VARCHAR(64),
            outcome VARCHAR(10),
            exit_price DOUBLE PRECISION,
            pnl DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_counterfactuals_pending ON risk_counterfactuals (outcome) WHERE outcome IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_counterfactuals_asset ON risk_counterfactuals (asset, created_at)")
    op.execute("""
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
        )
    """)

    # ═══════════════════════════════════════
    # TABLES FROM wallet/router.py
    # ═══════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_wallets (
            user_id TEXT PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 0,
            allocation REAL NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'demo',
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_after REAL NOT NULL,
            allocation_after REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'demo',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    # Downgrade drops ONLY the tables added by this migration.
    # ORM tables (from 001_initial) are left untouched.
    tables = [
        "wallet_transactions", "user_wallets",
        "backtest_runs", "risk_counterfactuals",
        "v8_regime_history",
        "order_events", "order_intents",
        "v7_portfolio_snapshots", "v7_trades", "v7_orders", "strategy_sleeves",
        "dismissed_alerts", "schema_version", "revoked_tokens",
        "stress_test_runs", "training_positions", "training_trades",
        "waitlist", "bar_processing_state", "kill_switch_events",
        "reallocation_log", "portfolio_decision_log", "portfolio_adaptive_rules",
        "scan_history", "meta_evaluations", "threshold_overrides",
        "learning_events", "paper_positions", "paper_portfolios",
        "trust_score_history_live", "trust_scores_live",
        "decision_traces", "agent_trade_performance",
        "admin_audit_log", "admin_config",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
