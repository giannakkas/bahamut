"""
Bahamut.AI — Adaptive Risk Engine

Dynamically adjusts risk thresholds based on recent market conditions.
All adjustments are bounded within safe limits and logged.

Inputs: recent volatility, drawdown trends, win/loss streaks, regime
Outputs: adjusted tail_risk_threshold, exposure_limits, confidence_requirements
"""
import structlog

logger = structlog.get_logger()

# Hard bounds — adaptive engine CANNOT exceed these
HARD_BOUNDS = {
    "tail_risk_threshold": (0.08, 0.25),     # min 8%, max 25%
    "gross_exposure_max": (0.40, 1.00),       # min 40%, max 100%
    "confidence_min_trade": (0.40, 0.80),     # min 40%, max 80%
}

# Default base values
BASE_VALUES = {
    "tail_risk_threshold": 0.25,
    "gross_exposure_max": 0.80,
    "confidence_min_trade": 0.58,
}


def compute_adaptive_adjustments() -> dict:
    """Compute adaptive risk adjustments based on current conditions."""
    conditions = _assess_conditions()
    adjustments = _calculate_adjustments(conditions)
    state = {
        "conditions": conditions,
        "adjustments": adjustments,
        "applied": _format_applied(adjustments),
    }

    if any(a["delta"] != 0 for a in adjustments.values()):
        logger.info("adaptive_risk_adjustment",
                     volatility=conditions["volatility_level"],
                     drawdown=conditions["drawdown_trend"],
                     streak=conditions["streak"])

    return state


def get_adaptive_threshold(key: str) -> float:
    """Get a single adaptively-adjusted threshold value."""
    state = compute_adaptive_adjustments()
    adj = state["adjustments"].get(key, {})
    return adj.get("adjusted", BASE_VALUES.get(key, 0))


def _assess_conditions() -> dict:
    """Assess current market/portfolio conditions."""
    conditions = {
        "volatility_level": "normal",   # low, normal, high, extreme
        "drawdown_trend": "stable",     # improving, stable, worsening
        "streak": 0,                    # positive = winning, negative = losing
        "recent_win_rate": 0.5,
        "regime": "unknown",
    }

    try:
        from bahamut.db.query import run_query, run_query_one

        # Win/loss streak from recent positions
        recent = run_query("""
            SELECT realized_pnl FROM paper_positions
            WHERE status != 'OPEN' AND realized_pnl IS NOT NULL
            ORDER BY closed_at DESC LIMIT 10
        """)
        if recent:
            wins = sum(1 for r in recent if float(r.get("realized_pnl", 0)) > 0)
            conditions["recent_win_rate"] = wins / len(recent)
            # Compute streak
            streak = 0
            for r in recent:
                pnl = float(r.get("realized_pnl", 0))
                if pnl > 0:
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                elif pnl < 0:
                    if streak <= 0:
                        streak -= 1
                    else:
                        break
            conditions["streak"] = streak

        # Drawdown trend
        pf = run_query_one(
            "SELECT total_pnl, current_balance, initial_balance FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
        )
        if pf:
            dd = float(pf.get("total_pnl", 0)) / max(float(pf.get("initial_balance", 100000)), 1)
            if dd < -0.05:
                conditions["drawdown_trend"] = "worsening"
            elif dd > 0.02:
                conditions["drawdown_trend"] = "improving"

        # Volatility from regime (simplified)
        regime = run_query_one(
            "SELECT regime FROM consensus_decisions ORDER BY created_at DESC LIMIT 1"
        )
        if regime:
            r = regime.get("regime", "")
            conditions["regime"] = r
            if r in ("HIGH_VOL", "CRISIS"):
                conditions["volatility_level"] = "high"
            elif r in ("LOW_VOL", "TREND_CONTINUATION"):
                conditions["volatility_level"] = "low"

    except Exception as e:
        logger.warning("adaptive_conditions_failed", error=str(e))

    return conditions


def _calculate_adjustments(conditions: dict) -> dict:
    """Calculate bounded threshold adjustments."""
    adjustments = {}

    vol = conditions["volatility_level"]
    dd = conditions["drawdown_trend"]
    streak = conditions["streak"]

    # ── Tail risk threshold ──
    base = BASE_VALUES["tail_risk_threshold"]
    delta = 0
    if vol == "high":
        delta -= 0.02  # tighten
    elif vol == "low" and dd == "improving":
        delta += 0.01  # slightly relax
    if streak <= -3:
        delta -= 0.02  # losing streak → tighten
    adjusted = _clamp(base + delta, *HARD_BOUNDS["tail_risk_threshold"])
    adjustments["tail_risk_threshold"] = {
        "base": base, "delta": round(delta, 4), "adjusted": adjusted,
        "reason": _explain_adjustment("tail_risk", vol, dd, streak),
    }

    # ── Gross exposure ──
    base = BASE_VALUES["gross_exposure_max"]
    delta = 0
    if vol == "high":
        delta -= 0.15
    elif vol == "low" and dd != "worsening":
        delta += 0.05
    if dd == "worsening":
        delta -= 0.10
    adjusted = _clamp(base + delta, *HARD_BOUNDS["gross_exposure_max"])
    adjustments["gross_exposure_max"] = {
        "base": base, "delta": round(delta, 4), "adjusted": adjusted,
        "reason": _explain_adjustment("exposure", vol, dd, streak),
    }

    # ── Confidence threshold ──
    base = BASE_VALUES["confidence_min_trade"]
    delta = 0
    if vol == "high":
        delta += 0.05  # require higher confidence in volatile markets
    if streak <= -3:
        delta += 0.03
    elif streak >= 5 and dd == "improving":
        delta -= 0.03
    adjusted = _clamp(base + delta, *HARD_BOUNDS["confidence_min_trade"])
    adjustments["confidence_min_trade"] = {
        "base": base, "delta": round(delta, 4), "adjusted": adjusted,
        "reason": _explain_adjustment("confidence", vol, dd, streak),
    }

    return adjustments


def _clamp(value, min_val, max_val):
    return round(max(min_val, min(max_val, value)), 4)


def _explain_adjustment(param, vol, dd, streak):
    parts = []
    if vol == "high":
        parts.append("high volatility detected")
    elif vol == "low":
        parts.append("low volatility environment")
    if dd == "worsening":
        parts.append("drawdown trend worsening")
    elif dd == "improving":
        parts.append("drawdown trend improving")
    if streak <= -3:
        parts.append(f"losing streak ({streak})")
    elif streak >= 5:
        parts.append(f"winning streak ({streak})")
    if not parts:
        return "no adjustment needed"
    return "; ".join(parts)
