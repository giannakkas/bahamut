"""
Bahamut.AI — Adaptive Risk Engine

Dynamically adjusts risk thresholds based on ACTUAL training trade outcomes.
All adjustments bounded within hard limits and logged.

Data source: training_trades table + Redis training stats.
Requires MIN_TRADES_FOR_ADAPTIVE closed trades before making adjustments.

Inputs: recent win/loss streaks, drawdown, regime conditions
Outputs: adjusted tail_risk_threshold, exposure_limits, confidence_requirements
"""
import structlog

logger = structlog.get_logger()

HARD_BOUNDS = {
    "tail_risk_threshold": (0.08, 0.25),
    "gross_exposure_max": (0.40, 1.00),
    "confidence_min_trade": (0.40, 0.80),
}

BASE_VALUES = {
    "tail_risk_threshold": 0.25,
    "gross_exposure_max": 0.80,
    "confidence_min_trade": 0.58,
}

MIN_TRADES_FOR_ADAPTIVE = 25


def compute_adaptive_adjustments() -> dict:
    """Compute adaptive risk adjustments from real training trade data."""
    conditions = _assess_conditions()
    active = conditions.get("trades_available", 0) >= MIN_TRADES_FOR_ADAPTIVE

    if not active:
        # Not enough data — return base values with explanation
        return {
            "active": False,
            "reason": f"Insufficient data ({conditions.get('trades_available', 0)}/{MIN_TRADES_FOR_ADAPTIVE} trades)",
            "conditions": conditions,
            "adjustments": {
                k: {"base": v, "delta": 0, "adjusted": v, "reason": "adaptive inactive — warming up"}
                for k, v in BASE_VALUES.items()
            },
            "applied": {k: v for k, v in BASE_VALUES.items()},
        }

    adjustments = _calculate_adjustments(conditions)
    return {
        "active": True,
        "reason": f"Based on {conditions.get('trades_available', 0)} training trades",
        "conditions": conditions,
        "adjustments": adjustments,
        "applied": {k: v["adjusted"] for k, v in adjustments.items()},
    }


def get_adaptive_threshold(key: str) -> float:
    """Get a single adaptively-adjusted threshold value."""
    state = compute_adaptive_adjustments()
    return state["applied"].get(key, BASE_VALUES.get(key, 0))


def _assess_conditions() -> dict:
    """Assess conditions from real training trade outcomes."""
    conditions = {
        "trades_available": 0,
        "volatility_level": "normal",
        "drawdown_trend": "stable",
        "streak": 0,
        "recent_win_rate": 0.5,
        "regime": "unknown",
    }

    # Try DB: training_trades
    try:
        from bahamut.db.query import run_query, run_query_one

        # Total count
        row = run_query_one("SELECT COUNT(*) as cnt FROM training_trades")
        total = int(row.get("cnt", 0)) if row else 0
        conditions["trades_available"] = total

        if total < 5:
            return conditions

        # Recent 10 trades for streak + win rate
        recent = run_query("""
            SELECT pnl FROM training_trades
            ORDER BY created_at DESC LIMIT 10
        """)
        if recent:
            pnls = [float(r.get("pnl", 0)) for r in recent]
            wins = sum(1 for p in pnls if p > 0)
            conditions["recent_win_rate"] = wins / len(pnls)

            # Streak
            streak = 0
            for p in pnls:
                if p > 0:
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                elif p < 0:
                    if streak <= 0:
                        streak -= 1
                    else:
                        break
            conditions["streak"] = streak

        # Drawdown from total PnL
        pnl_row = run_query_one("SELECT SUM(pnl) as total_pnl FROM training_trades")
        if pnl_row:
            total_pnl = float(pnl_row.get("total_pnl", 0) or 0)
            from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL
            dd_pct = total_pnl / TRAINING_VIRTUAL_CAPITAL
            if dd_pct < -0.05:
                conditions["drawdown_trend"] = "worsening"
            elif dd_pct > 0.02:
                conditions["drawdown_trend"] = "improving"

        # Volatility from recent trade variance
        if recent and len(recent) >= 5:
            pnls_abs = [abs(p) for p in pnls]
            avg_move = sum(pnls_abs) / len(pnls_abs)
            if avg_move > 200:
                conditions["volatility_level"] = "high"
            elif avg_move < 30:
                conditions["volatility_level"] = "low"

        # Regime from portfolio manager
        try:
            from bahamut.portfolio.manager import get_cross_process_regimes
            regimes = get_cross_process_regimes()
            if regimes:
                conditions["regime"] = list(regimes.values())[0]
        except Exception:
            pass

    except Exception as e:
        logger.debug("adaptive_conditions_failed", error=str(e))

    # Fallback: Redis stats
    if conditions["trades_available"] == 0:
        try:
            import os, json, redis
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            total = 0
            for strat in ["v5_base", "v5_tuned", "v9_breakout"]:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    s = json.loads(raw)
                    total += s.get("trades", 0)
            conditions["trades_available"] = total
        except Exception:
            pass

    return conditions


def _calculate_adjustments(conditions: dict) -> dict:
    adjustments = {}
    vol = conditions["volatility_level"]
    dd = conditions["drawdown_trend"]
    streak = conditions["streak"]

    # Tail risk
    base = BASE_VALUES["tail_risk_threshold"]
    delta = 0
    if vol == "high":
        delta -= 0.02
    elif vol == "low" and dd == "improving":
        delta += 0.01
    if streak <= -3:
        delta -= 0.02
    adjusted = _clamp(base + delta, *HARD_BOUNDS["tail_risk_threshold"])
    adjustments["tail_risk_threshold"] = {
        "base": base, "delta": round(delta, 4), "adjusted": adjusted,
        "reason": _explain(vol, dd, streak),
    }

    # Gross exposure
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
        "reason": _explain(vol, dd, streak),
    }

    # Confidence threshold
    base = BASE_VALUES["confidence_min_trade"]
    delta = 0
    if vol == "high":
        delta += 0.05
    if streak <= -3:
        delta += 0.03
    elif streak >= 5 and dd == "improving":
        delta -= 0.03
    adjusted = _clamp(base + delta, *HARD_BOUNDS["confidence_min_trade"])
    adjustments["confidence_min_trade"] = {
        "base": base, "delta": round(delta, 4), "adjusted": adjusted,
        "reason": _explain(vol, dd, streak),
    }

    return adjustments


def _clamp(value, min_val, max_val):
    return round(max(min_val, min(max_val, value)), 4)


def _explain(vol, dd, streak):
    parts = []
    if vol != "normal":
        parts.append(f"{vol} volatility")
    if dd != "stable":
        parts.append(f"drawdown {dd}")
    if abs(streak) >= 3:
        parts.append(f"{'winning' if streak > 0 else 'losing'} streak ({streak})")
    return "; ".join(parts) if parts else "no adjustment needed"
