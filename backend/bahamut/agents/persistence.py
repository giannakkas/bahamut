"""Save signal cycle results to PostgreSQL for trade journal and history."""
import json
from datetime import datetime, timezone
from uuid import UUID
import structlog
from sqlalchemy import text
from bahamut.config import get_settings
from bahamut.database import sync_engine

def ensure_tables():
    """Initialize all tables via centralized schema management."""
    from bahamut.db.schema.tables import init_schema
    init_schema()


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
                 agent_contributions, dissenting_agents, risk_flags, disagreement_metrics)
                VALUES (:id, :cycle_id, :asset, :dir, :score, :decision, :agreement,
                        :regime, :profile, :mode, :blocked, :explanation,
                        :contributions, :dissenters, :flags, :disagreement)
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
                "disagreement": json.dumps(decision.get("disagreement")),
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


def save_decision_trace(result: dict):
    """Save full decision context for learning replay."""
    import json
    try:
        decision = result.get("decision", {})
        cycle_id = result.get("cycle_id", "")
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO decision_traces
                (cycle_id, asset, timeframe, trading_profile, execution_mode,
                 regime, regime_confidence, agent_outputs, consensus_output,
                 disagreement_metrics, trust_scores_at_decision)
                VALUES (:cid, :asset, :tf, :profile, :mode,
                        :regime, :rc, :agents, :consensus, :disagree, :trust)
            """), {
                "cid": cycle_id, "asset": decision.get("asset", ""),
                "tf": "4H", "profile": decision.get("trading_profile", "BALANCED"),
                "mode": decision.get("execution_mode", "WATCH"),
                "regime": decision.get("regime", "UNKNOWN"),
                "rc": decision.get("regime_confidence", 0),
                "agents": json.dumps(result.get("agent_outputs", []), default=str),
                "consensus": json.dumps(decision, default=str),
                "disagree": json.dumps(result.get("disagreement"), default=str),
                "trust": json.dumps(
                    {c["agent_id"]: c.get("trust_score", 1.0)
                     for c in decision.get("agent_contributions", [])}, default=str),
            })
            conn.commit()
    except Exception as e:
        logger.error("decision_trace_failed", error=str(e))


def link_trace_to_position(cycle_id: str, position_id: int):
    try:
        with sync_engine.connect() as conn:
            conn.execute(text(
                "UPDATE decision_traces SET position_id = :pid WHERE cycle_id = :cid AND position_id IS NULL"
            ), {"pid": position_id, "cid": cycle_id})
            conn.commit()
    except Exception as e:
        logger.error("link_trace_failed", error=str(e))


def close_decision_trace(cycle_id: str, outcome: dict):
    import json
    try:
        with sync_engine.connect() as conn:
            conn.execute(text(
                "UPDATE decision_traces SET outcome = :o, closed_at = NOW() WHERE cycle_id = :cid"
            ), {"o": json.dumps(outcome, default=str), "cid": cycle_id})
            conn.commit()
    except Exception as e:
        logger.error("close_trace_failed", error=str(e))


def save_scan_results(results: dict):
    """Save scan results to PostgreSQL for history."""
    import json
    try:
        with sync_engine.connect() as conn:
            pass  # Schema managed by db.schema.tables
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
            pass  # Schema managed by db.schema.tables
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
