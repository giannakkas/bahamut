"""Save signal cycle results to PostgreSQL for trade journal and history."""
import json
from datetime import datetime, timezone
from uuid import UUID
import structlog
from sqlalchemy import text
from bahamut.config import get_settings
from bahamut.database import sync_engine

def ensure_tables():
    """Create tables if they don't exist."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS signal_cycles (
                    id VARCHAR PRIMARY KEY,
                    asset VARCHAR(20),
                    timeframe VARCHAR(10),
                    triggered_by VARCHAR(20) DEFAULT 'SCHEDULE',
                    status VARCHAR(20) DEFAULT 'COMPLETED',
                    started_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS consensus_decisions (
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
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_outputs (
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
                )
            """))
            conn.commit()
            
            # Paper trading tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_portfolios (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) DEFAULT 'SYSTEM_DEMO',
                    initial_balance FLOAT DEFAULT 100000,
                    current_balance FLOAT DEFAULT 100000,
                    total_pnl FLOAT DEFAULT 0,
                    total_pnl_pct FLOAT DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    win_rate FLOAT DEFAULT 0,
                    best_trade_pnl FLOAT DEFAULT 0,
                    worst_trade_pnl FLOAT DEFAULT 0,
                    max_drawdown FLOAT DEFAULT 0,
                    peak_balance FLOAT DEFAULT 100000,
                    is_active BOOLEAN DEFAULT TRUE,
                    risk_per_trade_pct FLOAT DEFAULT 2.0,
                    max_open_positions INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_positions (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_trade_performance (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_events (
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
                )
            """))
            conn.commit()
            logger.info("persistence_tables_ensured")

            # Paper trading tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_portfolios (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) DEFAULT 'SYSTEM_DEMO',
                    initial_balance FLOAT DEFAULT 100000,
                    current_balance FLOAT DEFAULT 100000,
                    total_pnl FLOAT DEFAULT 0,
                    total_pnl_pct FLOAT DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    win_rate FLOAT DEFAULT 0,
                    best_trade_pnl FLOAT DEFAULT 0,
                    worst_trade_pnl FLOAT DEFAULT 0,
                    max_drawdown FLOAT DEFAULT 0,
                    peak_balance FLOAT DEFAULT 100000,
                    is_active BOOLEAN DEFAULT TRUE,
                    risk_per_trade_pct FLOAT DEFAULT 2.0,
                    max_open_positions INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_positions (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_trade_performance (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_events (
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
                )
            """))
            conn.commit()
            logger.info("paper_trading_tables_ensured")

            # Paper trading tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_portfolios (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_positions (
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
                    unrealized_pnl FLOAT DEFAULT 0.0,
                    unrealized_pnl_pct FLOAT DEFAULT 0.0,
                    exit_price FLOAT,
                    realized_pnl FLOAT,
                    realized_pnl_pct FLOAT,
                    status VARCHAR(20) DEFAULT 'OPEN',
                    agent_votes JSONB NOT NULL,
                    consensus_score FLOAT NOT NULL,
                    cycle_id VARCHAR(100),
                    opened_at TIMESTAMP DEFAULT NOW(),
                    closed_at TIMESTAMP,
                    max_favorable FLOAT DEFAULT 0.0,
                    max_adverse FLOAT DEFAULT 0.0,
                    learning_processed BOOLEAN DEFAULT FALSE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_trade_performance (
                    id SERIAL PRIMARY KEY,
                    agent_name VARCHAR(50) NOT NULL,
                    asset VARCHAR(20) NOT NULL,
                    total_signals INTEGER DEFAULT 0,
                    correct_signals INTEGER DEFAULT 0,
                    wrong_signals INTEGER DEFAULT 0,
                    neutral_signals INTEGER DEFAULT 0,
                    accuracy FLOAT DEFAULT 0.0,
                    profit_factor FLOAT DEFAULT 0.0,
                    avg_confidence_when_correct FLOAT DEFAULT 0.0,
                    avg_confidence_when_wrong FLOAT DEFAULT 0.0,
                    total_pnl_when_agreed FLOAT DEFAULT 0.0,
                    total_pnl_when_disagreed FLOAT DEFAULT 0.0,
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    worst_streak INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT NOW(),
                    UNIQUE(agent_name, asset)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_events (
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
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_paper_positions_status ON paper_positions(status);
                CREATE INDEX IF NOT EXISTS ix_paper_positions_asset ON paper_positions(asset);
                CREATE INDEX IF NOT EXISTS ix_paper_positions_opened_at ON paper_positions(opened_at);
                CREATE INDEX IF NOT EXISTS ix_agent_perf_name_asset ON agent_trade_performance(agent_name, asset);
                CREATE INDEX IF NOT EXISTS ix_learning_events_agent ON learning_events(agent_name);
                CREATE INDEX IF NOT EXISTS ix_learning_events_created ON learning_events(created_at);
            """))
            conn.commit()
            logger.info("paper_trading_tables_ensured")

            # Paper trading tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_portfolios (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) DEFAULT 'SYSTEM_DEMO',
                    initial_balance FLOAT DEFAULT 100000,
                    current_balance FLOAT DEFAULT 100000,
                    total_pnl FLOAT DEFAULT 0,
                    total_pnl_pct FLOAT DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    win_rate FLOAT DEFAULT 0,
                    best_trade_pnl FLOAT DEFAULT 0,
                    worst_trade_pnl FLOAT DEFAULT 0,
                    max_drawdown FLOAT DEFAULT 0,
                    peak_balance FLOAT DEFAULT 100000,
                    is_active BOOLEAN DEFAULT TRUE,
                    risk_per_trade_pct FLOAT DEFAULT 2.0,
                    max_open_positions INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_positions (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_trade_performance (
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS learning_events (
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
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_paper_positions_status ON paper_positions(status);
                CREATE INDEX IF NOT EXISTS ix_paper_positions_asset ON paper_positions(asset);
                CREATE INDEX IF NOT EXISTS ix_paper_positions_opened_at ON paper_positions(opened_at);
                CREATE INDEX IF NOT EXISTS ix_agent_perf_name_asset ON agent_trade_performance(agent_name, asset);
                CREATE INDEX IF NOT EXISTS ix_learning_events_agent ON learning_events(agent_name);
                CREATE INDEX IF NOT EXISTS ix_learning_events_created ON learning_events(created_at);
            """))
            conn.commit()
            logger.info("paper_trading_tables_ensured")
    except Exception as e:
        logger.error("table_creation_failed", error=str(e))

logger = structlog.get_logger()
settings = get_settings()


def save_cycle_to_db(result: dict):
    """Persist a complete signal cycle result to the database."""
    ensure_tables()
    try:
        decision = result.get("decision", {})
        cycle_id = result.get("cycle_id", "")
        asset = decision.get("asset", "unknown")

        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO signal_cycles (id, asset, timeframe, triggered_by, status, started_at, completed_at)
                VALUES (:id, :asset, :timeframe, :triggered_by, 'COMPLETED', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": cycle_id,
                "asset": asset,
                "timeframe": decision.get("timeframe", "4H"),
                "triggered_by": "SCHEDULE",
            })

            # Save consensus decision
            conn.execute(text("""
                INSERT INTO consensus_decisions
                (id, cycle_id, asset, direction, final_score, decision, agreement_pct,
                 regime, trading_profile, execution_mode, blocked, explanation,
                 agent_contributions, dissenting_agents, risk_flags)
                VALUES (:id, :cycle_id, :asset, :dir, :score, :decision, :agreement,
                        :regime, :profile, :mode, :blocked, :explanation,
                        :contributions, :dissenters, :flags)
                ON CONFLICT DO NOTHING
            """), {
                "id": decision.get("consensus_id", cycle_id),
                "cycle_id": cycle_id,
                "asset": asset,
                "dir": decision.get("direction", "NO_TRADE"),
                "score": decision.get("final_score", 0),
                "decision": decision.get("decision", "NO_TRADE"),
                "agreement": decision.get("agreement_pct", 0),
                "regime": decision.get("regime", "UNKNOWN"),
                "profile": decision.get("trading_profile", "BALANCED"),
                "mode": decision.get("execution_mode", "WATCH"),
                "blocked": decision.get("blocked", False),
                "explanation": decision.get("explanation", ""),
                "contributions": json.dumps(decision.get("agent_contributions", [])),
                "dissenters": json.dumps(decision.get("dissenting_agents", [])),
                "flags": json.dumps(decision.get("risk_flags", [])),
            })

            # Save each agent output
            for output in result.get("agent_outputs", []):
                conn.execute(text("""
                    INSERT INTO agent_outputs
                    (id, cycle_id, agent_id, directional_bias, confidence,
                     evidence, risk_notes, invalidation_conditions, meta)
                    VALUES (gen_random_uuid(), :cycle_id, :agent_id, :bias, :confidence,
                            :evidence, :risk_notes, :invalidation, :meta)
                    ON CONFLICT DO NOTHING
                """), {
                    "cycle_id": cycle_id,
                    "agent_id": output.get("agent_id", ""),
                    "bias": output.get("directional_bias", "NEUTRAL"),
                    "confidence": output.get("confidence", 0),
                    "evidence": json.dumps(output.get("evidence", [])),
                    "risk_notes": json.dumps(output.get("risk_notes", [])),
                    "invalidation": json.dumps(output.get("invalidation_conditions", [])),
                    "meta": json.dumps(output.get("meta", {})),
                })

            conn.commit()
            logger.info("cycle_persisted", cycle_id=cycle_id, asset=asset,
                        direction=decision.get("direction"))

    except Exception as e:
        logger.error("cycle_persist_failed", error=str(e))


def save_scan_results(results: dict):
    """Save scan results to PostgreSQL for history."""
    import json
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id SERIAL PRIMARY KEY,
                    scanned_at TIMESTAMP DEFAULT NOW(),
                    total_scanned INTEGER DEFAULT 0,
                    elapsed_sec FLOAT DEFAULT 0,
                    timeframe VARCHAR(10) DEFAULT '4h',
                    results JSONB NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO scan_history (scanned_at, total_scanned, elapsed_sec, timeframe, results)
                VALUES (NOW(), :total, :elapsed, :tf, CAST(:results AS jsonb))
            """), {
                "total": results.get("total_scanned", 0),
                "elapsed": results.get("elapsed_sec", 0),
                "tf": results.get("timeframe", "4h"),
                "results": json.dumps(results, default=str),
            })
            conn.commit()
            logger.info("scan_results_saved", total=results.get("total_scanned", 0))
    except Exception as e:
        logger.error("save_scan_failed", error=str(e))


def get_latest_scan() -> dict | None:
    """Get the most recent scan from DB (fallback when Redis is empty)."""
    import json
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id SERIAL PRIMARY KEY,
                    scanned_at TIMESTAMP DEFAULT NOW(),
                    total_scanned INTEGER DEFAULT 0,
                    elapsed_sec FLOAT DEFAULT 0,
                    timeframe VARCHAR(10) DEFAULT '4h',
                    results JSONB NOT NULL
                )
            """))
            conn.commit()
            result = conn.execute(text(
                "SELECT results FROM scan_history ORDER BY scanned_at DESC LIMIT 1"
            ))
            row = result.first()
            if row:
                return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception as e:
        logger.error("get_scan_failed", error=str(e))
    return None
