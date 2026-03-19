"""
Bahamut.AI System Confidence

Composite 0–1 score computed from 4 real signals:

  system_confidence =
    0.30 × trust_stability      +   # are trust scores stable or oscillating?
    0.25 × disagreement_trend   +   # is disagreement rising or falling?
    0.30 × recent_performance   +   # are recent trades profitable?
    0.15 × calibration_health       # is the system calibrating regularly?

Each component independently maps to 0–1.
Score cached in Redis for 60s. Recomputed on every cycle if stale.

Plugs into:
  - Execution policy (replaces simple mean_trust for gating + sizing)
  - Consensus engine (score dampening)
  - Stored on positions for learning attribution
"""
import time
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()

WEIGHTS = {
    "trust_stability": 0.30,
    "disagreement_trend": 0.25,
    "recent_performance": 0.30,
    "calibration_health": 0.15,
}

_cache: dict = {"value": None, "components": None, "computed_at": 0}
CACHE_TTL = 60  # seconds


@dataclass
class ConfidenceBreakdown:
    system_confidence: float = 0.5
    trust_stability: float = 0.5
    disagreement_trend: float = 0.5
    recent_performance: float = 0.5
    calibration_health: float = 0.5
    mean_agent_trust: float = 1.0    # kept for backward compat
    computed_at: float = 0.0

    def to_dict(self):
        return {
            "system_confidence": round(self.system_confidence, 4),
            "trust_stability": round(self.trust_stability, 4),
            "disagreement_trend": round(self.disagreement_trend, 4),
            "recent_performance": round(self.recent_performance, 4),
            "calibration_health": round(self.calibration_health, 4),
            "mean_agent_trust": round(self.mean_agent_trust, 4),
            "computed_at": self.computed_at,
        }


def get_system_confidence() -> ConfidenceBreakdown:
    """Get current system confidence (cached 60s)."""
    now = time.time()
    if _cache["value"] is not None and (now - _cache["computed_at"]) < CACHE_TTL:
        return _cache["value"]
    return compute_system_confidence()


def compute_system_confidence() -> ConfidenceBreakdown:
    """Compute fresh system confidence from 4 DB queries."""
    bd = ConfidenceBreakdown(computed_at=time.time())

    bd.trust_stability = _compute_trust_stability()
    bd.disagreement_trend = _compute_disagreement_trend()
    bd.recent_performance = _compute_recent_performance()
    bd.calibration_health = _compute_calibration_health()

    # Also grab mean_agent_trust for backward compat
    bd.mean_agent_trust = _compute_mean_trust()

    bd.system_confidence = round(
        WEIGHTS["trust_stability"] * bd.trust_stability
        + WEIGHTS["disagreement_trend"] * bd.disagreement_trend
        + WEIGHTS["recent_performance"] * bd.recent_performance
        + WEIGHTS["calibration_health"] * bd.calibration_health,
        4,
    )

    _cache["value"] = bd
    _cache["computed_at"] = bd.computed_at

    logger.info("system_confidence_computed",
                confidence=bd.system_confidence,
                trust_stab=bd.trust_stability,
                disagree=bd.disagreement_trend,
                perf=bd.recent_performance,
                calib=bd.calibration_health)
    return bd


def _compute_trust_stability() -> float:
    """
    Trust stability: low variance in recent trust changes = stable = high score.
    Measures std dev of (new_score - old_score) over last 7 days.
    Stable (stddev < 0.02) → 1.0, Volatile (stddev > 0.10) → 0.2
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT new_score - old_score as delta
                FROM trust_score_history_live
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC LIMIT 200
            """)).all()
            if len(rows) < 5:
                return 0.5  # insufficient data

            deltas = [float(r[0]) for r in rows]
            mean_d = sum(deltas) / len(deltas)
            variance = sum((d - mean_d) ** 2 for d in deltas) / len(deltas)
            stddev = variance ** 0.5

            # Map: stddev 0→1.0, 0.02→0.9, 0.05→0.7, 0.10→0.2
            if stddev < 0.01:
                return 1.0
            elif stddev < 0.03:
                return 0.9
            elif stddev < 0.06:
                return 0.7
            elif stddev < 0.10:
                return 0.4
            else:
                return 0.2
    except Exception as e:
        logger.warning("confidence_component_failed", error=str(e))
        return 0.5


def _compute_disagreement_trend() -> float:
    """
    Disagreement trend: is disagreement rising or falling over recent cycles?
    Compares avg disagreement in last 12h vs last 48h.
    Falling disagreement = agents converging = high score.
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            recent = conn.execute(text("""
                SELECT AVG((disagreement_metrics->>'disagreement_index')::float) as avg_d
                FROM consensus_decisions
                WHERE created_at > NOW() - INTERVAL '12 hours'
                AND disagreement_metrics IS NOT NULL
            """)).scalar()
            baseline = conn.execute(text("""
                SELECT AVG((disagreement_metrics->>'disagreement_index')::float) as avg_d
                FROM consensus_decisions
                WHERE created_at > NOW() - INTERVAL '48 hours'
                AND disagreement_metrics IS NOT NULL
            """)).scalar()

            if recent is None or baseline is None:
                return 0.5

            recent_f = float(recent)
            baseline_f = float(baseline)

            # Low absolute disagreement = good
            level_score = max(0.0, 1.0 - recent_f * 1.5)  # 0.0→1.0, 0.3→0.55, 0.6→0.1

            # Falling trend = good, rising = bad
            if baseline_f > 0.01:
                trend_ratio = recent_f / baseline_f
                if trend_ratio < 0.8:
                    trend_bonus = 0.15  # improving
                elif trend_ratio > 1.2:
                    trend_bonus = -0.15  # worsening
                else:
                    trend_bonus = 0.0
            else:
                trend_bonus = 0.0

            return max(0.0, min(1.0, round(level_score + trend_bonus, 4)))
    except Exception as e:
        logger.warning("confidence_component_failed", error=str(e))
        return 0.5


def _compute_recent_performance() -> float:
    """
    Recent performance: 7-day win rate and profit factor.
    50% win rate + PF 1.0 → 0.5 (breakeven)
    60% win rate + PF 1.5 → 0.85 (good)
    <35% win rate → 0.1 (bad)
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                       COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) as gross_w,
                       COALESCE(ABS(SUM(realized_pnl) FILTER (WHERE realized_pnl < 0)), 0.01) as gross_l
                FROM paper_positions
                WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '7 days'
            """)).mappings().first()
            if not r or r["total"] < 3:
                return 0.5  # insufficient

            total = r["total"]
            wr = r["wins"] / total
            pf = float(r["gross_w"]) / float(r["gross_l"])

            # Win rate component: 0.35→0.1, 0.50→0.5, 0.60→0.75, 0.70→0.9
            if wr >= 0.65:
                wr_score = 0.9
            elif wr >= 0.55:
                wr_score = 0.7
            elif wr >= 0.45:
                wr_score = 0.5
            elif wr >= 0.35:
                wr_score = 0.25
            else:
                wr_score = 0.1

            # Profit factor component: <0.8→0.1, 1.0→0.4, 1.5→0.8, 2.0→1.0
            pf_score = max(0.0, min(1.0, (pf - 0.5) / 1.5))

            return round(wr_score * 0.6 + pf_score * 0.4, 4)
    except Exception as e:
        logger.warning("confidence_component_failed", error=str(e))
        return 0.5


def _compute_calibration_health() -> float:
    """
    Calibration health: is the system maintaining itself?
    - Last calibration < 24h → 1.0
    - Last calibration < 48h → 0.7
    - Last calibration < 96h → 0.4
    - Never / >96h → 0.1
    Also checks if calibrations are producing stable results (not flip-flopping).
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT MAX(started_at) as last_run,
                       COUNT(*) as total_runs,
                       COUNT(*) FILTER (WHERE notes LIKE '%%ALERT%%' OR notes LIKE '%%emergency%%') as alert_runs
                FROM calibration_runs
                WHERE started_at > NOW() - INTERVAL '7 days'
            """)).mappings().first()

            if not r or not r["last_run"]:
                return 0.1

            from datetime import datetime, timezone
            last = r["last_run"]
            if hasattr(last, 'replace'):
                last = last.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600

            # Recency score
            if age_hours <= 24:
                recency = 1.0
            elif age_hours <= 48:
                recency = 0.7
            elif age_hours <= 96:
                recency = 0.4
            else:
                recency = 0.1

            # Stability: many alerts = unstable
            total = r["total_runs"] or 1
            alert_ratio = (r["alert_runs"] or 0) / total
            stability = max(0.3, 1.0 - alert_ratio * 2)

            return round(recency * 0.7 + stability * 0.3, 4)
    except Exception as e:
        logger.warning("confidence_component_failed", error=str(e))
        return 0.5


def _compute_mean_trust() -> float:
    """Simple mean of global trust scores (backward compat)."""
    try:
        from bahamut.consensus.trust_store import trust_store
        scores = []
        for aid in ["technical_agent", "macro_agent", "sentiment_agent",
                     "volatility_agent", "liquidity_agent"]:
            sc, _ = trust_store.get(aid, "global")
            scores.append(sc)
        return sum(scores) / len(scores) if scores else 1.0
    except Exception as e:
        logger.warning("confidence_component_failed", error=str(e))
        return 1.0
