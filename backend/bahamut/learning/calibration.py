"""
Bahamut.AI Recalibration Engine

Runs: after N trades, daily, weekly, on drawdown spikes, manually.
Adjusts: trust normalization, threshold recommendations, regime snapshots.
Persists calibration_runs with version history.
"""
import json
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class CalibrationResult:
    cadence: str = ""
    status: str = "completed"
    trades_analyzed: int = 0
    threshold_changes: dict = field(default_factory=dict)
    precision_scores: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def run_daily_calibration() -> CalibrationResult:
    from bahamut.consensus.trust_store import trust_store
    result = CalibrationResult(cadence="daily")
    notes = []

    trust_store.apply_daily_decay(decay_rate=0.005)
    notes.append("Applied daily trust decay (0.005)")

    accuracy = _compute_recent_accuracy(7)
    result.precision_scores = accuracy
    total = accuracy.get("total_trades", 0)

    if total >= 5:
        wr = accuracy.get("win_rate", 0)
        if wr < 0.35:
            notes.append(f"ALERT: Win rate {wr:.1%} — tighten thresholds")
            result.threshold_changes["recommendation"] = "tighten"
        elif wr > 0.70:
            notes.append(f"Win rate {wr:.1%} — may be too conservative")
            result.threshold_changes["recommendation"] = "loosen_candidate"
        else:
            notes.append(f"Win rate {wr:.1%} — no change needed")
            result.threshold_changes["recommendation"] = "hold"
    else:
        notes.append(f"Only {total} trades — insufficient for analysis")

    result.trades_analyzed = total
    result.notes = notes
    _save_calibration_run(result)
    logger.info("daily_calibration", trades=total, notes=notes)
    return result


def run_weekly_calibration() -> CalibrationResult:
    result = CalibrationResult(cadence="weekly")
    notes = []
    accuracy = _compute_recent_accuracy(30)
    agent_acc = _compute_per_agent_accuracy(30)
    result.precision_scores = accuracy
    result.trades_analyzed = accuracy.get("total_trades", 0)

    for agent, stats in agent_acc.items():
        if stats["total"] >= 10 and stats["accuracy"] < 0.40:
            notes.append(f"{agent} underperforming: {stats['accuracy']:.1%}")
        elif stats["total"] >= 10 and stats["accuracy"] > 0.65:
            notes.append(f"{agent} strong: {stats['accuracy']:.1%}")

    result.notes = notes
    _save_calibration_run(result)
    return result


def run_emergency_calibration(reason: str = "manual") -> CalibrationResult:
    from bahamut.consensus.trust_store import trust_store
    result = CalibrationResult(cadence="emergency", notes=[f"Emergency: {reason}"])
    trust_store.apply_daily_decay(decay_rate=0.05)
    result.notes.append("Applied aggressive decay (0.05)")
    _save_calibration_run(result)
    logger.warning("emergency_calibration", reason=reason)
    return result


def run_trade_triggered_calibration(threshold: int = 20) -> CalibrationResult | None:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FROM paper_positions WHERE status != 'OPEN'
                AND closed_at > COALESCE(
                    (SELECT MAX(started_at) FROM calibration_runs WHERE cadence = 'trade_triggered'),
                    '2000-01-01')
            """))
            if (r.scalar() or 0) >= threshold:
                return run_daily_calibration()
    except Exception as e:
        logger.error("trade_trigger_failed", error=str(e))
    return None


def _compute_recent_accuracy(days: int) -> dict:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text(f"""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                       COALESCE(AVG(realized_pnl_pct), 0) as avg_pnl,
                       COALESCE(AVG(consensus_score), 0) as avg_score
                FROM paper_positions
                WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '{days} days'
            """))
            row = r.mappings().first()
            if not row or row["total"] == 0:
                return {"total_trades": 0, "win_rate": 0}
            return {
                "total_trades": row["total"], "wins": row["wins"],
                "win_rate": row["wins"] / row["total"],
                "avg_pnl_pct": round(float(row["avg_pnl"]), 3),
            }
    except Exception as e:
        return {"total_trades": 0, "error": str(e)}


def _compute_per_agent_accuracy(days: int) -> dict:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text(f"""
                SELECT agent_name, COUNT(*) as total,
                       COUNT(*) FILTER (WHERE was_correct = true) as correct
                FROM learning_events WHERE created_at > NOW() - INTERVAL '{days} days'
                AND was_correct IS NOT NULL GROUP BY agent_name
            """))
            return {row["agent_name"]: {"total": row["total"], "correct": row["correct"],
                    "accuracy": row["correct"] / row["total"] if row["total"] > 0 else 0}
                    for row in r.mappings().all()}
    except Exception:
        return {}


def _save_calibration_run(result: CalibrationResult):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS calibration_runs (
                    id SERIAL PRIMARY KEY, cadence VARCHAR(20), started_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP DEFAULT NOW(), status VARCHAR(20) DEFAULT 'completed',
                    trades_analyzed INTEGER DEFAULT 0, threshold_changes JSONB,
                    precision_scores JSONB, notes TEXT, created_at TIMESTAMP DEFAULT NOW())
            """))
            conn.execute(text("""
                INSERT INTO calibration_runs (cadence, status, trades_analyzed, threshold_changes, precision_scores, notes)
                VALUES (:c, :s, :t, :th, :p, :n)
            """), {"c": result.cadence, "s": result.status, "t": result.trades_analyzed,
                   "th": json.dumps(result.threshold_changes), "p": json.dumps(result.precision_scores),
                   "n": "\n".join(result.notes)})
            conn.commit()
    except Exception as e:
        logger.error("save_calibration_failed", error=str(e))
