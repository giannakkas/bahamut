"""
Bahamut.AI Meta-Learning Engine — system-level self-evaluation.

Runs periodically. Analyzes:
  1. Rolling performance windows (7d, 30d, 90d)
  2. Trend detection: is the system improving or degrading?
  3. Drawdown patterns: streaks, regime-correlated losses
  4. Agent consensus quality: do high-agreement signals actually win more?
  5. Corrective actions: tighten/loosen thresholds, trigger emergency calibration

Outputs a SystemHealthReport that feeds into adaptive profile + threshold tuning.
"""
import json
import time
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class PerformanceWindow:
    window_days: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    total_pnl: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_losses: int = 0
    avg_consensus_score_winners: float = 0.0
    avg_consensus_score_losers: float = 0.0


@dataclass
class SystemHealthReport:
    generated_at: float = 0.0
    windows: dict = field(default_factory=dict)  # {7: PerformanceWindow, 30: ..., 90: ...}
    trend: str = "STABLE"                         # IMPROVING, DEGRADING, STABLE, COLD_START
    trend_score: float = 0.0                      # -1.0 (bad) to +1.0 (good)
    consensus_quality: float = 0.0                # correlation between score and win rate
    agent_diversity_score: float = 0.0            # are agents providing diverse opinions?
    recommended_actions: list = field(default_factory=list)
    risk_level: str = "NORMAL"                    # LOW, NORMAL, ELEVATED, CRITICAL

    def to_dict(self):
        return {
            "generated_at": self.generated_at,
            "windows": {str(k): vars(v) for k, v in self.windows.items()},
            "trend": self.trend, "trend_score": round(self.trend_score, 3),
            "consensus_quality": round(self.consensus_quality, 3),
            "agent_diversity_score": round(self.agent_diversity_score, 3),
            "recommended_actions": self.recommended_actions,
            "risk_level": self.risk_level,
        }


_last_report: SystemHealthReport | None = None


def run_meta_evaluation() -> SystemHealthReport:
    """Run full system-level evaluation. Called by daily calibration."""
    global _last_report
    report = SystemHealthReport(generated_at=time.time())

    # 1. Compute rolling windows
    for days in [7, 30, 90]:
        report.windows[days] = _compute_window(days)

    # 2. Trend detection
    w7 = report.windows.get(7, PerformanceWindow())
    w30 = report.windows.get(30, PerformanceWindow())
    w90 = report.windows.get(90, PerformanceWindow())

    if w30.total_trades < 5:
        report.trend = "COLD_START"
        report.trend_score = 0.0
    else:
        # Compare recent (7d) vs baseline (30d)
        if w7.total_trades >= 3 and w30.total_trades >= 10:
            wr_delta = w7.win_rate - w30.win_rate
            pf_delta = w7.profit_factor - w30.profit_factor
            report.trend_score = round(wr_delta * 0.6 + min(1.0, max(-1.0, pf_delta * 0.2)) * 0.4, 3)
            if report.trend_score > 0.05:
                report.trend = "IMPROVING"
            elif report.trend_score < -0.10:
                report.trend = "DEGRADING"
            else:
                report.trend = "STABLE"
        else:
            report.trend = "COLD_START"

    # 3. Consensus quality — do higher scores actually produce better trades?
    report.consensus_quality = _compute_consensus_quality()

    # 4. Agent diversity
    report.agent_diversity_score = _compute_agent_diversity()

    # 5. Risk level + corrective actions
    actions = []

    if w7.max_consecutive_losses >= 5:
        report.risk_level = "CRITICAL"
        actions.append({"action": "EMERGENCY_CALIBRATE", "reason": f"{w7.max_consecutive_losses} consecutive losses in 7d"})
    elif w7.total_trades >= 3 and w7.win_rate < 0.25:
        report.risk_level = "ELEVATED"
        actions.append({"action": "TIGHTEN_THRESHOLDS", "reason": f"7d win rate {w7.win_rate:.1%}"})
    elif report.trend == "DEGRADING":
        report.risk_level = "ELEVATED"
        actions.append({"action": "TIGHTEN_THRESHOLDS", "reason": f"Degrading trend ({report.trend_score:+.3f})"})

    if report.consensus_quality < 0.1 and w30.total_trades >= 15:
        actions.append({"action": "RECALIBRATE_WEIGHTS", "reason": f"Consensus quality {report.consensus_quality:.2f} — scores don't predict outcomes"})

    if w30.total_trades >= 20 and w30.win_rate > 0.60 and w30.profit_factor > 1.5:
        actions.append({"action": "LOOSEN_CANDIDATE", "reason": f"30d win rate {w30.win_rate:.1%}, PF {w30.profit_factor:.1f}"})

    if report.agent_diversity_score < 0.3 and w30.total_trades >= 10:
        actions.append({"action": "CHECK_AGENT_DIVERSITY", "reason": "Agents producing uniform opinions — weak signal quality"})

    report.recommended_actions = actions
    _last_report = report
    _persist_report(report)
    logger.info("meta_evaluation", trend=report.trend, score=report.trend_score,
                 risk=report.risk_level, actions=len(actions))
    return report


def get_last_report() -> SystemHealthReport | None:
    return _last_report


def _compute_window(days: int) -> PerformanceWindow:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text(f"""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                       COUNT(*) FILTER (WHERE realized_pnl <= 0) as losses,
                       COALESCE(AVG(realized_pnl_pct), 0) as avg_pnl,
                       COALESCE(SUM(realized_pnl), 0) as total_pnl,
                       COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) as gross_w,
                       COALESCE(ABS(SUM(realized_pnl) FILTER (WHERE realized_pnl < 0)), 0.01) as gross_l,
                       COALESCE(AVG(consensus_score) FILTER (WHERE realized_pnl > 0), 0) as avg_score_w,
                       COALESCE(AVG(consensus_score) FILTER (WHERE realized_pnl <= 0), 0) as avg_score_l
                FROM paper_positions
                WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '{days} days'
            """)).mappings().first()
            if not r or r["total"] == 0:
                return PerformanceWindow(window_days=days)

            total = r["total"]
            wins = r["wins"]
            return PerformanceWindow(
                window_days=days, total_trades=total, wins=wins, losses=r["losses"],
                win_rate=round(wins / total, 3) if total > 0 else 0,
                avg_pnl_pct=round(float(r["avg_pnl"]), 3),
                total_pnl=round(float(r["total_pnl"]), 2),
                profit_factor=round(float(r["gross_w"]) / float(r["gross_l"]), 2),
                max_consecutive_losses=_max_consecutive_losses(conn, days),
                avg_consensus_score_winners=round(float(r["avg_score_w"]), 3),
                avg_consensus_score_losers=round(float(r["avg_score_l"]), 3),
            )
    except Exception as e:
        logger.debug("window_compute_failed", days=days, error=str(e))
        return PerformanceWindow(window_days=days)


def _max_consecutive_losses(conn, days: int) -> int:
    from sqlalchemy import text
    try:
        rows = conn.execute(text(f"""
            SELECT realized_pnl FROM paper_positions
            WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '{days} days'
            ORDER BY closed_at
        """)).all()
        max_streak, cur = 0, 0
        for row in rows:
            if float(row[0]) <= 0:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        return max_streak
    except Exception as e:

        logger.warning("learning_meta_silent_error", error=str(e))
        return 0


def _compute_consensus_quality() -> float:
    """Do higher consensus scores predict higher win rates? Returns 0-1."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT consensus_score, realized_pnl FROM paper_positions
                WHERE status != 'OPEN' AND consensus_score > 0
                ORDER BY consensus_score
            """)).all()
            if len(rows) < 10:
                return 0.5
            # Split into low-score and high-score halves
            mid = len(rows) // 2
            low_wr = sum(1 for r in rows[:mid] if float(r[1]) > 0) / mid
            high_wr = sum(1 for r in rows[mid:] if float(r[1]) > 0) / (len(rows) - mid)
            # Quality = how much better high-score trades are
            return round(max(0.0, min(1.0, 0.5 + (high_wr - low_wr))), 3)
    except Exception as e:

        logger.warning("learning_meta_silent_error", error=str(e))
        return 0.5


def _compute_agent_diversity() -> float:
    """Are agents providing diverse opinions or herding? Returns 0-1."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT AVG(agreement_pct) as avg_agree
                FROM consensus_decisions
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)).mappings().first()
            if not r or r["avg_agree"] is None:
                return 0.5
            avg = float(r["avg_agree"])
            # High agreement (>0.9) = low diversity = bad for signal quality
            # Moderate agreement (0.5-0.7) = good diversity
            if avg > 0.9:
                return round(0.2, 3)
            elif avg > 0.8:
                return round(0.5, 3)
            elif avg > 0.6:
                return round(0.8, 3)
            else:
                return round(1.0, 3)
    except Exception as e:

        logger.warning("learning_meta_silent_error", error=str(e))
        return 0.5


def _persist_report(report: SystemHealthReport):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS meta_evaluations (
                    id SERIAL PRIMARY KEY, generated_at TIMESTAMP DEFAULT NOW(),
                    trend VARCHAR(20), trend_score FLOAT, risk_level VARCHAR(20),
                    consensus_quality FLOAT, agent_diversity FLOAT,
                    windows JSONB, recommended_actions JSONB, created_at TIMESTAMP DEFAULT NOW())
            """))
            conn.execute(text("""
                INSERT INTO meta_evaluations
                (trend, trend_score, risk_level, consensus_quality, agent_diversity, windows, recommended_actions)
                VALUES (:t, :ts, :rl, :cq, :ad, :w, :ra)
            """), {
                "t": report.trend, "ts": report.trend_score,
                "rl": report.risk_level, "cq": report.consensus_quality,
                "ad": report.agent_diversity_score,
                "w": json.dumps({str(k): vars(v) for k, v in report.windows.items()}),
                "ra": json.dumps(report.recommended_actions),
            })
            conn.commit()
    except Exception as e:
        logger.warning("meta_persist_failed", error=str(e))
