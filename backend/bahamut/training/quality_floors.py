"""
Bahamut — Quality Floors (Pre-Ranking Hard Gates)

Runs AFTER context gate and suppression check, BEFORE additive scoring.
Ensures weak candidates cannot be rescued by accumulating partial points.

Floor checks:
  A) Readiness floor — minimum setup quality score
  B) Reward/Risk floor — minimum R:R ratio
  C) Trust floor — minimum effective trust for mature patterns
  D) Expectancy floor — minimum rolling expectancy for developing+ patterns
  E) Regime alignment floor — strategy must suit current regime

Each floor returns pass/fail with a structured reason.
Training mode has softer floors than production.
"""
import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# CONFIGURATION — training vs production
# ═══════════════════════════════════════════

FLOORS = {
    "TRAINING": {
        "min_readiness": 25,           # Low floor for exploration
        "min_reward_risk": 1.2,        # At least 1.2:1 R:R
        "min_effective_trust": 0.15,   # Only blocks extremely bad mature patterns
        "min_expectancy": -0.40,       # Very generous — only blocks deeply negative
        "min_expectancy_samples": 8,   # Need 8+ trades for expectancy floor
    },
    "PRODUCTION": {
        "min_readiness": 45,
        "min_reward_risk": 1.5,
        "min_effective_trust": 0.25,
        "min_expectancy": -0.15,
        "min_expectancy_samples": 6,
    },
}


def get_floors(mode: str = "TRAINING") -> dict:
    return FLOORS.get(mode.upper(), FLOORS["TRAINING"])


# ═══════════════════════════════════════════
# QUALITY FLOOR CHECK
# ═══════════════════════════════════════════

def check_quality_floors(
    readiness_score: int,
    sl_pct: float,
    tp_pct: float,
    strategy: str,
    regime: str,
    asset_class: str,
    asset: str,
    mode: str = "TRAINING",
) -> dict:
    """Check all hard quality floors for a candidate.

    Returns:
      passed: bool
      action: "pass" | "reject" | "watchlist"
      failures: list[dict] — each with floor, value, threshold, reason
      summary: str — human-readable
    """
    floors = get_floors(mode)
    failures = []

    # ── A) Readiness floor ──
    min_r = floors["min_readiness"]
    if readiness_score < min_r:
        failures.append({
            "floor": "readiness",
            "value": readiness_score,
            "threshold": min_r,
            "reason": f"Readiness {readiness_score} < minimum {min_r}",
        })

    # ── B) Reward/Risk floor ──
    rr = tp_pct / max(sl_pct, 0.001)
    min_rr = floors["min_reward_risk"]
    if rr < min_rr:
        failures.append({
            "floor": "reward_risk",
            "value": round(rr, 2),
            "threshold": min_rr,
            "reason": f"R:R {rr:.2f} < minimum {min_rr}",
        })

    # ── C) Trust floor (only for non-provisional patterns) ──
    min_trust = floors["min_effective_trust"]
    try:
        from bahamut.training.learning_engine import get_pattern_trust
        trust = get_pattern_trust(strategy, regime, asset_class)

        effective_trust = trust["blended_trust"] * trust["blended_confidence"]
        maturity = trust["maturity"]

        # Only apply trust floor to developing+ patterns (provisional gets a pass)
        if maturity != "provisional" and effective_trust < min_trust:
            failures.append({
                "floor": "trust",
                "value": round(effective_trust, 3),
                "threshold": min_trust,
                "reason": f"Effective trust {effective_trust:.3f} < {min_trust} ({maturity})",
                "maturity": maturity,
            })

        # ── D) Expectancy floor ──
        min_exp = floors["min_expectancy"]
        min_exp_samples = floors["min_expectancy_samples"]
        expectancy = trust.get("expectancy", 0.0)
        total_trades = trust.get("total_trades", 0)

        if total_trades >= min_exp_samples and expectancy < min_exp:
            failures.append({
                "floor": "expectancy",
                "value": round(expectancy, 3),
                "threshold": min_exp,
                "reason": f"Expectancy {expectancy:.3f}R < {min_exp}R after {total_trades} trades",
                "maturity": maturity,
            })

        # ── D2) Mature pattern auto-suppress ──
        # Only auto-suppress when the SPECIFIC pattern (strategy+regime+class)
        # has 50+ trades. Don't use blended total_trades which inherits from
        # parent buckets — that blocks new pattern combos (like CRASH SHORTs)
        # using data from old patterns (like RANGE LONGs).
        pattern_trades = 0
        pattern_expectancy = 0.0
        buckets = trust.get("buckets", {})
        if "pattern" in buckets:
            pattern_trades = buckets["pattern"].get("samples", 0)
        # Also check class bucket as secondary
        if pattern_trades == 0 and "class" in buckets:
            pattern_trades = buckets["class"].get("samples", 0)

        if pattern_trades >= 50:
            # Use pattern-level expectancy if available, else blended
            pattern_expectancy = trust.get("expectancy", 0.0)
            if pattern_expectancy < -0.05:
                failures.append({
                    "floor": "expectancy_mature",
                    "value": round(pattern_expectancy, 3),
                    "threshold": -0.05,
                    "reason": f"Mature pattern ({pattern_trades} trades) negative expectancy {pattern_expectancy:.3f}R — auto-suppressed",
                    "maturity": maturity,
                })

    except Exception:
        pass  # Trust unavailable — skip trust/expectancy floors

    # ── Decision ──
    if not failures:
        return {
            "passed": True,
            "action": "pass",
            "failures": [],
            "summary": "All quality floors passed",
        }

    # Determine action: reject vs watchlist
    # In training mode, borderline failures → watchlist. Hard failures → reject.
    hard_failures = [f for f in failures if f["floor"] in ("trust", "expectancy", "expectancy_mature")]
    soft_failures = [f for f in failures if f["floor"] in ("readiness", "reward_risk")]

    if hard_failures:
        action = "reject"
    elif mode == "TRAINING" and all(f["floor"] in ("readiness",) for f in failures):
        # In training, low readiness alone → watchlist (borderline)
        action = "watchlist"
    else:
        action = "reject" if mode == "PRODUCTION" else "watchlist"

    reasons = [f["reason"] for f in failures]
    floor_names = [f["floor"] for f in failures]

    logger.info(f"selector_quality_{'blocked' if action == 'reject' else 'watchlisted'}",
                asset=asset, strategy=strategy, regime=regime,
                action=action, floors_failed=floor_names,
                readiness=readiness_score, rr=round(rr, 2),
                mode=mode)

    return {
        "passed": False,
        "action": action,
        "failures": failures,
        "summary": " + ".join(reasons),
    }
