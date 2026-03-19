"""
Bahamut.AI — Centralized Schema Definitions

SINGLE SOURCE OF TRUTH for all table schemas.
All CREATE TABLE logic lives here. No other module should define table schemas.

Table Ownership Map:
  ┌──────────────────────────────┬──────────────────────────────────┐
  │ Table                        │ Canonical Writer Module           │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ agent_outputs                │ agents/persistence.py            │
  │ agent_trade_performance      │ agents/persistence.py            │
  │ consensus_decisions          │ agents/persistence.py            │
  │ decision_traces              │ agents/persistence.py            │
  │ signal_cycles                │ agents/persistence.py            │
  │ scan_history                 │ agents/persistence.py            │
  │ learning_events              │ agents/persistence.py            │
  │ trust_scores_live            │ consensus/trust_store.py         │
  │ trust_score_history_live     │ consensus/trust_store.py         │
  │ calibration_runs             │ learning/calibration.py          │
  │ regime_snapshots             │ learning/calibration.py          │
  │ threshold_overrides          │ learning/thresholds.py           │
  │ meta_evaluations             │ learning/meta.py                 │
  │ paper_portfolios             │ paper_trading/store.py           │
  │ paper_positions              │ paper_trading/store.py           │
  │ portfolio_adaptive_rules     │ portfolio/learning.py            │
  │ portfolio_decision_log       │ portfolio/learning.py            │
  │ reallocation_log             │ portfolio/allocator.py           │
  │ kill_switch_events           │ portfolio/kill_switch.py         │
  │ stress_test_runs             │ stress/engine.py                 │
  │ admin_config                 │ admin/config.py                  │
  │ admin_audit_log              │ admin/config.py                  │
  └──────────────────────────────┴──────────────────────────────────┘
"""
import structlog

logger = structlog.get_logger()

# Schema version — bump when adding new tables or altering schemas
SCHEMA_VERSION = 3

# ─── All CREATE TABLE statements in dependency order ───

TABLES = [
    # ── Admin ──
    """CREATE TABLE IF NOT EXISTS admin_config (
        key VARCHAR(100) PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS admin_audit_log (
        id SERIAL PRIMARY KEY,
        config_key VARCHAR(100),
        old_value TEXT,
        new_value TEXT,
        changed_by VARCHAR(50) DEFAULT 'system',
        action VARCHAR(20) DEFAULT 'set',
        created_at TIMESTAMP DEFAULT NOW()
    )""",

    # ── Agent Pipeline ──
    """CREATE TABLE IF NOT EXISTS agent_outputs (
        id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
        cycle_id VARCHAR,
        agent_id VARCHAR(30),
        directional_bias VARCHAR(20),
        confidence FLOAT,
        evidence JSONB,
        risk_notes JSONB,
        invalidation_conditions JSONB,
        meta JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS agent_trade_performance (
        id SERIAL PRIMARY KEY,
        agent_name VARCHAR(50) NOT NULL,
        asset VARCHAR(20) NOT NULL,
        total_signals INTEGER DEFAULT 0,
        correct_signals INTEGER DEFAULT 0,
        wrong_signals INTEGER DEFAULT 0,
        neutral_signals INTEGER DEFAULT 0,
        accuracy FLOAT DEFAULT 0,
        profit_factor FLOAT DEFAULT 0,
        avg_confidence_when_correct FLOAT DEFAULT 0,
        avg_confidence_when_wrong FLOAT DEFAULT 0,
        total_pnl_when_agreed FLOAT DEFAULT 0,
        total_pnl_when_disagreed FLOAT DEFAULT 0,
        current_streak INTEGER DEFAULT 0,
        best_streak INTEGER DEFAULT 0,
        worst_streak INTEGER DEFAULT 0,
        last_updated TIMESTAMP DEFAULT NOW(),
        UNIQUE(agent_name, asset)
    )""",
    """CREATE TABLE IF NOT EXISTS signal_cycles (
        id VARCHAR PRIMARY KEY,
        asset VARCHAR(20),
        timeframe VARCHAR(10),
        triggered_by VARCHAR(20) DEFAULT 'SCHEDULE',
        status VARCHAR(20) DEFAULT 'COMPLETED',
        started_at TIMESTAMP DEFAULT NOW(),
        completed_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS consensus_decisions (
        id VARCHAR PRIMARY KEY,
        cycle_id VARCHAR,
        asset VARCHAR(20),
        direction VARCHAR(20),
        final_score FLOAT DEFAULT 0,
        decision VARCHAR(30),
        agreement_pct FLOAT DEFAULT 0,
        regime VARCHAR(30),
        trading_profile VARCHAR(30),
        execution_mode VARCHAR(20),
        blocked BOOLEAN DEFAULT FALSE,
        explanation TEXT,
        agent_contributions JSONB,
        dissenting_agents JSONB,
        risk_flags JSONB,
        disagreement_metrics JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS decision_traces (
        id SERIAL PRIMARY KEY,
        cycle_id VARCHAR(100) NOT NULL,
        position_id INTEGER,
        asset VARCHAR(20) NOT NULL,
        timeframe VARCHAR(10) DEFAULT '4H',
        trading_profile VARCHAR(30),
        execution_mode VARCHAR(20),
        regime VARCHAR(50),
        regime_confidence FLOAT,
        agent_outputs JSONB NOT NULL,
        consensus_output JSONB NOT NULL,
        disagreement_metrics JSONB,
        trust_scores_at_decision JSONB,
        outcome JSONB,
        learning_applied BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        closed_at TIMESTAMP
    )""",

    # ── Trust Scores ──
    """CREATE TABLE IF NOT EXISTS trust_scores_live (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(50) NOT NULL,
        dimension VARCHAR(100) NOT NULL,
        score FLOAT DEFAULT 1.0,
        sample_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(agent_id, dimension)
    )""",
    """CREATE TABLE IF NOT EXISTS trust_score_history_live (
        id SERIAL PRIMARY KEY,
        agent_id VARCHAR(50),
        dimension VARCHAR(100),
        old_score FLOAT,
        new_score FLOAT,
        change_reason VARCHAR(50),
        trade_id VARCHAR(100),
        alpha_used FLOAT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",

    # ── Paper Trading ──
    """CREATE TABLE IF NOT EXISTS paper_portfolios (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) DEFAULT 'SYSTEM_DEMO' NOT NULL,
        initial_balance FLOAT DEFAULT 100000.0 NOT NULL,
        current_balance FLOAT DEFAULT 100000.0 NOT NULL,
        total_pnl FLOAT DEFAULT 0.0,
        total_pnl_pct FLOAT DEFAULT 0.0,
        total_trades INTEGER DEFAULT 0,
        winning_trades INTEGER DEFAULT 0,
        losing_trades INTEGER DEFAULT 0,
        win_rate FLOAT DEFAULT 0.0,
        best_trade_pnl FLOAT DEFAULT 0.0,
        worst_trade_pnl FLOAT DEFAULT 0.0,
        max_drawdown FLOAT DEFAULT 0.0,
        peak_balance FLOAT DEFAULT 100000.0,
        is_active BOOLEAN DEFAULT TRUE,
        risk_per_trade_pct FLOAT DEFAULT 2.0,
        max_open_positions INTEGER DEFAULT 5,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS paper_positions (
        id SERIAL PRIMARY KEY,
        portfolio_id INTEGER REFERENCES paper_portfolios(id),
        asset VARCHAR(20) NOT NULL,
        direction VARCHAR(10) NOT NULL,
        entry_price FLOAT NOT NULL,
        quantity FLOAT NOT NULL,
        position_value FLOAT NOT NULL,
        entry_signal_score FLOAT NOT NULL,
        entry_signal_label VARCHAR(30),
        stop_loss FLOAT NOT NULL,
        take_profit FLOAT NOT NULL,
        risk_amount FLOAT NOT NULL,
        atr_at_entry FLOAT,
        current_price FLOAT,
        unrealized_pnl FLOAT DEFAULT 0,
        unrealized_pnl_pct FLOAT DEFAULT 0,
        exit_price FLOAT,
        realized_pnl FLOAT,
        realized_pnl_pct FLOAT,
        status VARCHAR(20) DEFAULT 'OPEN',
        agent_votes JSONB NOT NULL,
        consensus_score FLOAT NOT NULL,
        cycle_id VARCHAR(100),
        opened_at TIMESTAMP DEFAULT NOW(),
        closed_at TIMESTAMP,
        max_favorable FLOAT DEFAULT 0,
        max_adverse FLOAT DEFAULT 0,
        learning_processed BOOLEAN DEFAULT FALSE
    )""",

    # ── Learning ──
    """CREATE TABLE IF NOT EXISTS learning_events (
        id SERIAL PRIMARY KEY,
        position_id INTEGER REFERENCES paper_positions(id),
        agent_name VARCHAR(50) NOT NULL,
        asset VARCHAR(20) NOT NULL,
        agent_direction VARCHAR(10),
        actual_outcome VARCHAR(10),
        agent_confidence FLOAT,
        was_correct BOOLEAN,
        trust_before FLOAT,
        trust_after FLOAT,
        trust_delta FLOAT,
        position_pnl FLOAT,
        position_pnl_pct FLOAT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS calibration_runs (
        id SERIAL PRIMARY KEY,
        cadence VARCHAR(20),
        started_at TIMESTAMP DEFAULT NOW(),
        completed_at TIMESTAMP DEFAULT NOW(),
        status VARCHAR(20) DEFAULT 'completed',
        trades_analyzed INTEGER DEFAULT 0,
        threshold_changes JSONB,
        precision_scores JSONB,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS regime_snapshots (
        id VARCHAR PRIMARY KEY,
        regime_id VARCHAR(100) UNIQUE,
        regime_type VARCHAR(50),
        start_date TIMESTAMP DEFAULT NOW(),
        end_date TIMESTAMP,
        feature_vector FLOAT[],
        agent_performance JSONB,
        optimal_weights JSONB,
        optimal_thresholds JSONB,
        total_trades INTEGER,
        win_rate FLOAT,
        avg_pnl_pct FLOAT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS threshold_overrides (
        id SERIAL PRIMARY KEY,
        profile VARCHAR(30) UNIQUE,
        thresholds JSONB,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS meta_evaluations (
        id SERIAL PRIMARY KEY,
        generated_at TIMESTAMP DEFAULT NOW(),
        trend VARCHAR(20),
        trend_score FLOAT,
        risk_level VARCHAR(20),
        consensus_quality FLOAT,
        agent_diversity FLOAT,
        windows JSONB,
        recommended_actions JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS scan_history (
        id SERIAL PRIMARY KEY,
        scanned_at TIMESTAMP DEFAULT NOW(),
        total_scanned INTEGER DEFAULT 0,
        elapsed_sec FLOAT DEFAULT 0,
        timeframe VARCHAR(10) DEFAULT '4h',
        results JSONB NOT NULL
    )""",

    # ── Portfolio Intelligence ──
    """CREATE TABLE IF NOT EXISTS portfolio_adaptive_rules (
        id SERIAL PRIMARY KEY,
        pattern_key VARCHAR(50) UNIQUE NOT NULL,
        adjustment_type VARCHAR(20),
        adjustment_value FLOAT DEFAULT 1.0,
        sample_count INTEGER DEFAULT 0,
        win_rate FLOAT DEFAULT 0.5,
        avg_pnl FLOAT DEFAULT 0,
        confidence FLOAT DEFAULT 0,
        active BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS portfolio_decision_log (
        id SERIAL PRIMARY KEY,
        position_id INTEGER,
        asset VARCHAR(20),
        direction VARCHAR(10),
        event_type VARCHAR(10),
        state JSONB,
        pnl FLOAT DEFAULT 0,
        exit_status VARCHAR(30),
        consensus_score FLOAT DEFAULT 0,
        portfolio_impact FLOAT DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS reallocation_log (
        id SERIAL PRIMARY KEY,
        position_id INTEGER,
        asset VARCHAR(20),
        direction VARCHAR(10),
        pnl FLOAT,
        reason TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS kill_switch_events (
        id SERIAL PRIMARY KEY,
        event_type VARCHAR(50),
        detail TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",

    # ── Stress Testing ──
    """CREATE TABLE IF NOT EXISTS stress_test_runs (
        id SERIAL PRIMARY KEY,
        scenario_name VARCHAR(100),
        mode VARCHAR(20),
        total_signals INTEGER,
        would_open INTEGER,
        would_block INTEGER,
        changed_decisions INTEGER,
        avg_size_mult FLOAT,
        blockers JSONB,
        warnings JSONB,
        elapsed_ms INTEGER,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""",

    # ── Token Revocation ──
    """CREATE TABLE IF NOT EXISTS revoked_tokens (
        id SERIAL PRIMARY KEY,
        jti VARCHAR(100) UNIQUE NOT NULL,
        user_id VARCHAR(100),
        revoked_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL
    )""",

    # ── Schema Version Tracking ──
    """CREATE TABLE IF NOT EXISTS schema_version (
        id SERIAL PRIMARY KEY,
        version INTEGER NOT NULL,
        applied_at TIMESTAMP DEFAULT NOW()
    )""",
]


def init_schema() -> None:
    """Initialize all tables and verify schema version. Called once at startup.

    - Creates all tables (idempotent via CREATE IF NOT EXISTS)
    - Checks DB schema version vs code version
    - Logs CRITICAL on version mismatch
    - Records new version on successful init
    """
    from bahamut.db.query import get_connection
    from sqlalchemy import text

    logger.info("schema_init_start", table_count=len(TABLES), code_version=SCHEMA_VERSION)
    errors = []
    with get_connection() as conn:
        for sql in TABLES:
            try:
                conn.execute(text(sql))
            except Exception as e:
                table_name = sql.split("(")[0].strip().split()[-1]
                errors.append(f"{table_name}: {str(e)[:80]}")
                logger.error("schema_init_table_failed", table=table_name, error=str(e))
        conn.commit()

        # ── Schema version check ──
        try:
            row = conn.execute(text(
                "SELECT MAX(version) FROM schema_version"
            )).fetchone()
            db_version = row[0] if row and row[0] else 0
        except Exception:
            db_version = 0

        if db_version > SCHEMA_VERSION:
            logger.critical("schema_version_mismatch",
                            msg="DB schema is NEWER than code — possible rollback or deployment error",
                            db_version=db_version, code_version=SCHEMA_VERSION)
            try:
                from bahamut.shared.degraded import mark_degraded
                mark_degraded("schema.version",
                              f"DB v{db_version} > code v{SCHEMA_VERSION}", ttl=600)
            except Exception:
                pass
        elif db_version < SCHEMA_VERSION:
            logger.info("schema_version_upgrade",
                        db_version=db_version, code_version=SCHEMA_VERSION)
            try:
                conn.execute(text(
                    "INSERT INTO schema_version (version) VALUES (:v)"
                ), {"v": SCHEMA_VERSION})
                conn.commit()
            except Exception as e:
                logger.warning("schema_version_record_failed", error=str(e))
        else:
            logger.info("schema_version_ok", version=SCHEMA_VERSION)

    if errors:
        logger.error("schema_init_partial_failure", errors=errors)
    else:
        logger.info("schema_init_complete", version=SCHEMA_VERSION)


def get_schema_status() -> dict:
    """Get schema version status for health endpoint."""
    try:
        from bahamut.db.query import get_connection
        from sqlalchemy import text
        with get_connection() as conn:
            row = conn.execute(text(
                "SELECT MAX(version) FROM schema_version"
            )).fetchone()
            db_version = row[0] if row and row[0] else 0

        if db_version == SCHEMA_VERSION:
            return {"status": "ok", "code_version": SCHEMA_VERSION, "db_version": db_version}
        elif db_version > SCHEMA_VERSION:
            return {"status": "mismatch", "code_version": SCHEMA_VERSION,
                    "db_version": db_version, "warning": "DB newer than code"}
        else:
            return {"status": "upgrading", "code_version": SCHEMA_VERSION,
                    "db_version": db_version}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}
