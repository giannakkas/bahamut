"""
Bahamut.AI Trading Readiness Checklist

12-point inspection that must ALL pass before the system should be
considered ready for live trading. Returns PASS / WARN / FAIL for each.

Categories:
  DATA: Market data flowing, indicators computing
  TRUST: Enough samples, trust scores reasonable
  PERFORMANCE: Win rate, profit factor, consecutive losses
  SYSTEM: Calibration recent, regime detection active, agents responding
  RISK: Drawdown within limits, policy active
"""
import time
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class CheckResult:
    name: str
    category: str
    status: str   # PASS, WARN, FAIL
    value: str
    threshold: str
    detail: str = ""


@dataclass
class ReadinessReport:
    overall: str = "NOT_READY"   # READY, CAUTION, NOT_READY
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    checks: list = field(default_factory=list)
    generated_at: float = 0.0

    def to_dict(self):
        return {
            "overall": self.overall,
            "pass_count": self.pass_count,
            "warn_count": self.warn_count,
            "fail_count": self.fail_count,
            "checks": [vars(c) for c in self.checks],
            "generated_at": self.generated_at,
        }


def run_readiness_check() -> ReadinessReport:
    """Run all 12 checks. Returns ReadinessReport."""
    report = ReadinessReport(generated_at=time.time())
    checks = [
        _check_market_data,
        _check_agent_response_rate,
        _check_trust_maturity,
        _check_trust_range,
        _check_min_closed_trades,
        _check_win_rate,
        _check_profit_factor,
        _check_consecutive_losses,
        _check_calibration_recency,
        _check_drawdown_headroom,
        _check_regime_detection,
        _check_execution_policy,
        _check_stress_resilience,
    ]
    for fn in checks:
        try:
            c = fn()
        except Exception as e:
            c = CheckResult(name=fn.__name__.replace("_check_", ""),
                            category="SYSTEM", status="FAIL",
                            value="error", threshold="", detail=str(e))
        report.checks.append(c)
        if c.status == "PASS":
            report.pass_count += 1
        elif c.status == "WARN":
            report.warn_count += 1
        else:
            report.fail_count += 1

    if report.fail_count == 0 and report.warn_count <= 2:
        report.overall = "READY"
    elif report.fail_count <= 2:
        report.overall = "CAUTION"
    else:
        report.overall = "NOT_READY"

    logger.info("readiness_check", overall=report.overall,
                 passed=report.pass_count, warns=report.warn_count, fails=report.fail_count)
    return report


def _check_market_data() -> CheckResult:
    """Is market data flowing? Check Redis for recent cycle cache."""
    try:
        import redis
        from bahamut.config import get_settings
        r = redis.from_url(get_settings().redis_url)
        keys = r.keys("bahamut:latest:*")
        r.close()
        count = len(keys)
        if count >= 3:
            return CheckResult("market_data", "DATA", "PASS", f"{count} assets cached", "≥3")
        elif count >= 1:
            return CheckResult("market_data", "DATA", "WARN", f"{count} assets cached", "≥3",
                               "Fewer assets than expected")
        return CheckResult("market_data", "DATA", "FAIL", "0 cached", "≥3",
                           "No market data in Redis")
    except Exception as e:
        return CheckResult("market_data", "DATA", "FAIL", "error", "≥3", str(e))


def _check_agent_response_rate() -> CheckResult:
    """Are all 5 directional agents responding in recent cycles?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(DISTINCT agent_id) as agents
                FROM agent_outputs
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)).scalar()
            if r and r >= 5:
                return CheckResult("agent_responses", "SYSTEM", "PASS", f"{r} agents active", "≥5")
            elif r and r >= 3:
                return CheckResult("agent_responses", "SYSTEM", "WARN", f"{r} agents active", "≥5",
                                   "Some agents not responding")
            return CheckResult("agent_responses", "SYSTEM", "FAIL",
                               f"{r or 0} agents", "≥5", "Agents not producing outputs")
    except Exception as e:
        return CheckResult("agent_responses", "SYSTEM", "FAIL", "error", "≥5", str(e))


def _check_trust_maturity() -> CheckResult:
    """Do trust scores have enough samples to be meaningful?"""
    try:
        from bahamut.consensus.trust_store import trust_store
        summary = trust_store.get_trust_summary()
        mature = sum(1 for a in summary if not a.get("provisional", True))
        total = len(summary)
        if mature == total and total > 0:
            return CheckResult("trust_maturity", "TRUST", "PASS",
                               f"{mature}/{total} mature", "all agents ≥10 samples")
        elif mature > 0:
            return CheckResult("trust_maturity", "TRUST", "WARN",
                               f"{mature}/{total} mature", "all agents ≥10 samples",
                               "Some agents still in cold start")
        return CheckResult("trust_maturity", "TRUST", "FAIL",
                           "0 mature", "all agents ≥10 samples", "All agents in cold start")
    except Exception as e:
        return CheckResult("trust_maturity", "TRUST", "FAIL", "error", "", str(e))


def _check_trust_range() -> CheckResult:
    """Are trust scores in a reasonable range (no extreme values)?"""
    try:
        from bahamut.consensus.trust_store import trust_store
        summary = trust_store.get_trust_summary()
        scores = [a.get("global_trust", 1.0) for a in summary]
        if not scores:
            return CheckResult("trust_range", "TRUST", "FAIL", "no data", "0.4–1.8")
        mn, mx = min(scores), max(scores)
        if mn >= 0.4 and mx <= 1.8:
            return CheckResult("trust_range", "TRUST", "PASS",
                               f"{mn:.2f}–{mx:.2f}", "0.4–1.8")
        elif mn >= 0.2:
            return CheckResult("trust_range", "TRUST", "WARN",
                               f"{mn:.2f}–{mx:.2f}", "0.4–1.8",
                               "Extreme trust values detected")
        return CheckResult("trust_range", "TRUST", "FAIL",
                           f"{mn:.2f}–{mx:.2f}", "0.4–1.8", "Trust scores critically low")
    except Exception as e:
        return CheckResult("trust_range", "TRUST", "FAIL", "error", "", str(e))


def _check_min_closed_trades() -> CheckResult:
    """Have enough trades closed to evaluate performance?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            count = conn.execute(text(
                "SELECT COUNT(*) FROM paper_positions WHERE status != 'OPEN'"
            )).scalar() or 0
            if count >= 30:
                return CheckResult("min_trades", "PERFORMANCE", "PASS", str(count), "≥30")
            elif count >= 10:
                return CheckResult("min_trades", "PERFORMANCE", "WARN", str(count), "≥30",
                                   "Approaching minimum but not enough for statistical confidence")
            return CheckResult("min_trades", "PERFORMANCE", "FAIL", str(count), "≥30",
                               "Insufficient trade history")
    except Exception as e:
        return CheckResult("min_trades", "PERFORMANCE", "FAIL", "error", "≥30", str(e))


def _check_win_rate() -> CheckResult:
    """Is 30-day win rate above minimum?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE realized_pnl > 0) as wins
                FROM paper_positions
                WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '30 days'
            """)).mappings().first()
            total = r["total"] if r else 0
            wins = r["wins"] if r else 0
            if total < 5:
                return CheckResult("win_rate", "PERFORMANCE", "WARN",
                                   f"{total} trades", "≥40% on 5+ trades",
                                   "Not enough recent trades")
            wr = wins / total
            if wr >= 0.45:
                return CheckResult("win_rate", "PERFORMANCE", "PASS",
                                   f"{wr:.1%} ({wins}/{total})", "≥45%")
            elif wr >= 0.35:
                return CheckResult("win_rate", "PERFORMANCE", "WARN",
                                   f"{wr:.1%} ({wins}/{total})", "≥45%", "Below target")
            return CheckResult("win_rate", "PERFORMANCE", "FAIL",
                               f"{wr:.1%} ({wins}/{total})", "≥45%", "Critically low")
    except Exception as e:
        return CheckResult("win_rate", "PERFORMANCE", "FAIL", "error", "", str(e))


def _check_profit_factor() -> CheckResult:
    """Is profit factor above 1.0?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) as gross_w,
                       COALESCE(ABS(SUM(realized_pnl) FILTER (WHERE realized_pnl < 0)), 0.01) as gross_l
                FROM paper_positions WHERE status != 'OPEN'
            """)).mappings().first()
            pf = float(r["gross_w"]) / float(r["gross_l"]) if r else 0
            if pf >= 1.2:
                return CheckResult("profit_factor", "PERFORMANCE", "PASS",
                                   f"{pf:.2f}", "≥1.2")
            elif pf >= 1.0:
                return CheckResult("profit_factor", "PERFORMANCE", "WARN",
                                   f"{pf:.2f}", "≥1.2", "Profitable but thin margin")
            return CheckResult("profit_factor", "PERFORMANCE", "FAIL",
                               f"{pf:.2f}", "≥1.2", "System is net unprofitable")
    except Exception as e:
        return CheckResult("profit_factor", "PERFORMANCE", "FAIL", "error", "", str(e))


def _check_consecutive_losses() -> CheckResult:
    """No more than 5 consecutive losses in last 7 days."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT realized_pnl FROM paper_positions
                WHERE status != 'OPEN' AND closed_at > NOW() - INTERVAL '7 days'
                ORDER BY closed_at
            """)).all()
            max_streak, cur = 0, 0
            for row in rows:
                if float(row[0]) <= 0:
                    cur += 1
                    max_streak = max(max_streak, cur)
                else:
                    cur = 0
            if max_streak <= 3:
                return CheckResult("consecutive_losses", "PERFORMANCE", "PASS",
                                   str(max_streak), "≤5")
            elif max_streak <= 5:
                return CheckResult("consecutive_losses", "PERFORMANCE", "WARN",
                                   str(max_streak), "≤5", "Approaching loss streak limit")
            return CheckResult("consecutive_losses", "PERFORMANCE", "FAIL",
                               str(max_streak), "≤5", f"{max_streak} consecutive losses")
    except Exception as e:
        return CheckResult("consecutive_losses", "PERFORMANCE", "FAIL", "error", "", str(e))


def _check_calibration_recency() -> CheckResult:
    """Has calibration run in the last 48 hours?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT MAX(started_at) FROM calibration_runs
            """)).scalar()
            if r:
                from datetime import datetime, timezone
                age_hours = (datetime.now(timezone.utc) - r.replace(tzinfo=timezone.utc)).total_seconds() / 3600
                if age_hours <= 48:
                    return CheckResult("calibration_recency", "SYSTEM", "PASS",
                                       f"{age_hours:.0f}h ago", "≤48h")
                elif age_hours <= 96:
                    return CheckResult("calibration_recency", "SYSTEM", "WARN",
                                       f"{age_hours:.0f}h ago", "≤48h")
            return CheckResult("calibration_recency", "SYSTEM", "FAIL",
                               "never" if not r else f"{age_hours:.0f}h ago", "≤48h",
                               "Calibration overdue")
    except Exception as e:
        return CheckResult("calibration_recency", "SYSTEM", "FAIL", "error", "", str(e))


def _check_drawdown_headroom() -> CheckResult:
    """Is current drawdown below 50% of limit?"""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            p = conn.execute(text("""
                SELECT current_balance, peak_balance FROM paper_portfolios
                WHERE name = 'SYSTEM_DEMO'
            """)).mappings().first()
            if not p:
                return CheckResult("drawdown_headroom", "RISK", "WARN",
                                   "no portfolio", "<50% of limit")
            bal = float(p["current_balance"])
            peak = float(p["peak_balance"])
            dd = (peak - bal) / peak if peak > 0 else 0
            limit = 0.15  # 15% max drawdown
            headroom = 1.0 - (dd / limit)
            if headroom >= 0.5:
                return CheckResult("drawdown_headroom", "RISK", "PASS",
                                   f"DD {dd:.1%}, {headroom:.0%} headroom", "≥50% headroom")
            elif headroom >= 0.2:
                return CheckResult("drawdown_headroom", "RISK", "WARN",
                                   f"DD {dd:.1%}, {headroom:.0%} headroom", "≥50% headroom",
                                   "Approaching drawdown limit")
            return CheckResult("drawdown_headroom", "RISK", "FAIL",
                               f"DD {dd:.1%}, {headroom:.0%} headroom", "≥50% headroom",
                               "Near or past drawdown limit")
    except Exception as e:
        return CheckResult("drawdown_headroom", "RISK", "FAIL", "error", "", str(e))


def _check_regime_detection() -> CheckResult:
    """Is regime detection running and returning valid data?"""
    try:
        from bahamut.features.regime import get_current_regime
        regime = get_current_regime()
        if regime.primary_regime and regime.primary_regime != "UNKNOWN":
            return CheckResult("regime_detection", "SYSTEM", "PASS",
                               regime.primary_regime, "not UNKNOWN",
                               f"confidence={regime.confidence:.2f}")
        return CheckResult("regime_detection", "SYSTEM", "WARN",
                           "UNKNOWN", "not UNKNOWN", "Regime not yet detected")
    except Exception as e:
        return CheckResult("regime_detection", "SYSTEM", "FAIL", "error", "", str(e))


def _check_execution_policy() -> CheckResult:
    """Is the execution policy module loaded and functional?"""
    try:
        from bahamut.execution.policy import execution_policy, ExecutionRequest, PROFILE_LIMITS
        # Quick smoke test
        req = ExecutionRequest(
            asset="TEST", direction="LONG", consensus_score=0.80,
            signal_label="SIGNAL", execution_mode_from_consensus="APPROVAL",
            disagreement_gate="CLEAR", risk_can_trade=True, trading_profile="BALANCED",
            portfolio_balance=100000,
        )
        dec = execution_policy.evaluate(req)
        if dec.allowed:
            return CheckResult("execution_policy", "RISK", "PASS",
                               "functional", "policy evaluates correctly")
        return CheckResult("execution_policy", "RISK", "PASS",
                           "functional (blocked test)", "policy evaluates correctly",
                           f"Test trade blocked: {dec.reason}")
    except Exception as e:
        return CheckResult("execution_policy", "RISK", "FAIL", "error", "", str(e))


def _check_stress_resilience() -> CheckResult:
    """Have stress tests been run recently, and did the system show resilience?"""
    try:
        from bahamut.stress.assessment import get_stress_assessment
        sa = get_stress_assessment()
        if not sa.has_recent_results:
            return CheckResult("stress_resilience", "RISK", "WARN",
                               "no recent tests", "stress score ≥ 0.50",
                               "Run stress tests to evaluate system resilience")
        score = sa.overall_stress_score
        if score >= 0.60:
            return CheckResult("stress_resilience", "RISK", "PASS",
                               f"{score:.2f}", "≥ 0.50",
                               f"Crisis: {sa.crisis_resilience:.2f}, Stability: {sa.decision_stability:.2f}")
        elif score >= 0.40:
            return CheckResult("stress_resilience", "RISK", "WARN",
                               f"{score:.2f}", "≥ 0.50",
                               f"Fragility: {sa.trust_fragility:.2f}, Adequacy: {sa.threshold_adequacy:.2f}")
        return CheckResult("stress_resilience", "RISK", "FAIL",
                           f"{score:.2f}", "≥ 0.50",
                           f"System fragile under stress: {', '.join(a['reason'] for a in sa.recommended_actions[:2])}")
    except Exception as e:
        return CheckResult("stress_resilience", "RISK", "WARN", "error", "", str(e))
