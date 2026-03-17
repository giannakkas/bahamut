"""Save signal cycle results to PostgreSQL for trade journal and history."""
import json
from datetime import datetime, timezone
from uuid import UUID
import structlog
from sqlalchemy import text
from bahamut.config import get_settings
from bahamut.database import sync_engine

logger = structlog.get_logger()
settings = get_settings()


def save_cycle_to_db(result: dict):
    """Persist a complete signal cycle result to the database."""
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
