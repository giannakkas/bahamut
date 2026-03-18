"""
Bahamut.AI Recalibration Engine

Runs: after N trades, daily, weekly, on drawdown spikes, manually.
Adjusts: trust normalization, threshold recommendations, regime snapshots.
Persists calibration_runs with version history.
"""
import json
import time
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

    # Run meta-learning evaluation
    try:
        from bahamut.learning.meta import run_meta_evaluation
        report = run_meta_evaluation()
        notes.append(f"Meta: trend={report.trend} score={report.trend_score:+.3f} risk={report.risk_level}")

        # Apply threshold tuning based on meta-learning
        if report.recommended_actions:
            from bahamut.learning.thresholds import apply_threshold_tuning
            changes = apply_threshold_tuning(report)
            if changes:
                result.threshold_changes = changes
                notes.append(f"Thresholds adjusted: {list(changes.keys())}")
            else:
                notes.append("Thresholds: no changes needed")

        # Emergency calibration trigger
        if report.risk_level == "CRITICAL":
            for action in report.recommended_actions:
                if action.get("action") == "EMERGENCY_CALIBRATE":
                    trust_store.apply_daily_decay(decay_rate=0.03)
                    notes.append(f"Emergency decay applied: {action.get('reason')}")
    except Exception as e:
        notes.append(f"Meta-learning skipped: {str(e)}")

    if total >= 5:
        wr = accuracy.get("win_rate", 0)
        if wr < 0.35:
            notes.append(f"ALERT: Win rate {wr:.1%}")
        elif wr > 0.70:
            notes.append(f"Win rate {wr:.1%} — strong")
    else:
        notes.append(f"Only {total} trades — insufficient")

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

    # Save regime snapshot if enough data
    if result.trades_analyzed >= 10:
        _save_regime_snapshot(agent_acc, accuracy)
        notes.append("Regime snapshot saved")

    result.notes = notes
    _save_calibration_run(result)
    return result


def run_emergency_calibration(reason: str = "manual") -> CalibrationResult:
    from bahamut.consensus.trust_store import trust_store
    result = CalibrationResult(cadence="emergency", notes=[f"Emergency: {reason}"])
    trust_store.apply_daily_decay(decay_rate=0.05)
    result.notes.append("Applied aggressive decay (0.05)")
    # Reset thresholds to safe defaults
    try:
        from bahamut.learning.thresholds import reset_to_defaults
        reset_to_defaults()
        result.notes.append("Thresholds reset to defaults")
    except Exception as e:
        result.notes.append(f"Threshold reset failed: {e}")
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


def _save_regime_snapshot(agent_acc: dict, accuracy: dict):
    """
    Save a regime snapshot with current agent performance and optimal weights.
    The weight_resolver reads from regime_snapshots to inform future decisions.
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        from bahamut.features.regime import get_current_regime
        from bahamut.consensus.trust_store import trust_store
        import uuid

        regime = get_current_regime()
        regime_type = regime.primary_regime

        # Compute optimal weights from current trust scores for this regime
        trust_scores = trust_store.get_scores_for_context(
            regime_type, "fx", "4H"  # Reference context
        )
        # Normalize trust to weights
        total_trust = sum(v for k, v in trust_scores.items() if k != "risk_agent") or 1.0
        optimal_weights = {
            k: round(v / total_trust, 4)
            for k, v in trust_scores.items() if k != "risk_agent"
        }

        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS regime_snapshots (
                    id VARCHAR PRIMARY KEY, regime_id VARCHAR(100) UNIQUE,
                    regime_type VARCHAR(50), start_date TIMESTAMP DEFAULT NOW(),
                    end_date TIMESTAMP, feature_vector FLOAT[],
                    agent_performance JSONB, optimal_weights JSONB,
                    optimal_thresholds JSONB, total_trades INTEGER,
                    win_rate FLOAT, avg_pnl_pct FLOAT, notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW())
            """))
            rid = f"{regime_type}_{int(time.time())}"
            conn.execute(text("""
                INSERT INTO regime_snapshots
                (id, regime_id, regime_type, feature_vector, agent_performance,
                 optimal_weights, optimal_thresholds, total_trades, win_rate, notes)
                VALUES (:id, :rid, :rt, :fv, :ap, :ow, :ot, :tt, :wr, :n)
                ON CONFLICT (regime_id) DO UPDATE SET
                    agent_performance = :ap, optimal_weights = :ow,
                    total_trades = :tt, win_rate = :wr
            """), {
                "id": str(uuid.uuid4()), "rid": rid, "rt": regime_type,
                "fv": regime.feature_vector,
                "ap": json.dumps(agent_acc, default=str),
                "ow": json.dumps(optimal_weights),
                "ot": json.dumps({}),
                "tt": accuracy.get("total_trades", 0),
                "wr": accuracy.get("win_rate", 0),
                "n": f"Auto-generated by weekly calibration",
            })
            conn.commit()
            logger.info("regime_snapshot_saved", regime=regime_type,
                         trades=accuracy.get("total_trades", 0))
    except Exception as e:
        logger.warning("regime_snapshot_failed", error=str(e))


def compute_per_regime_agent_accuracy(regime: str, days: int = 30) -> dict:
    """
    Compute per-agent accuracy filtered by regime.
    Uses learning_events + decision_traces to filter by regime at signal time.
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT le.agent_name,
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE le.was_correct = true) as correct
                FROM learning_events le
                JOIN decision_traces dt ON le.position_id IN (
                    SELECT pp.id FROM paper_positions pp
                    WHERE pp.cycle_id = dt.cycle_id
                )
                WHERE dt.regime = :regime
                  AND le.created_at > NOW() - INTERVAL :days
                  AND le.was_correct IS NOT NULL
                GROUP BY le.agent_name
            """).bindparams(regime=regime, days=f"{days} days"))
            return {row["agent_name"]: {"total": row["total"], "correct": row["correct"],
                    "accuracy": row["correct"] / row["total"] if row["total"] > 0 else 0}
                    for row in r.mappings().all()}
    except Exception as e:
        logger.debug("per_regime_accuracy_failed", error=str(e))
        return {}
