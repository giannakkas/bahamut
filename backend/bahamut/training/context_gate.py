"""
Bahamut — Context Gate & Pattern Suppression

Pre-scoring validation layer that blocks structurally invalid combinations
BEFORE they compete for priority. Also temporarily suppresses patterns
with proven poor performance.

Context Gate:
  Hard-blocks invalid strategy/regime combos (v10 in TREND, v9 in CRASH).
  Returns structured rejection reasons.

Pattern Suppression:
  Temporarily disables patterns with mature bad trust or repeated quick stops.
  Config-driven, auto-expires, logged for operator visibility.
"""
import json
import os
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# CONTEXT GATE — strategy/regime validation
# ═══════════════════════════════════════════

# Valid regime map: strategy → set of allowed regimes
# Anything not in the set is HARD BLOCKED before scoring
STRATEGY_REGIME_MAP = {
    "v5_base": {"TREND"},
    "v5_tuned": {"TREND"},
    "v9_breakout": {"TREND", "BREAKOUT", "RANGE"},  # RANGE allowed but penalized
    "v10_mean_reversion": {"RANGE", "CRASH"},        # CRASH allowed for SHORTs only
}

# Regimes that block LONGs for ALL strategies (SHORTs still allowed)
CRASH_LONG_BLOCKED = True

# Soft penalties: strategy+regime combos that are allowed but penalized
SOFT_PENALTY_COMBOS = {
    ("v9_breakout", "RANGE"): 10,  # v9 in RANGE = 10pt penalty
    ("v10_mean_reversion", "CRASH"): 5,  # v10 SHORT in CRASH = 5pt penalty (slightly risky)
}


def validate_strategy_context(strategy: str, regime: str, direction: str = "LONG",
                               mode: str = "TRAINING") -> dict:
    """Validate a strategy/regime/direction combination.

    Returns:
      valid: bool
      reason: str (empty if valid)
      penalty: int (soft penalty if valid but penalized)
      gate: str (which gate blocked/penalized)
    """
    result = {"valid": True, "reason": "", "penalty": 0, "gate": ""}

    # 1. CRASH regime: block LONGs, allow SHORTs for eligible strategies
    if regime == "CRASH":
        if direction == "LONG":
            return {
                "valid": False,
                "reason": f"CRASH regime blocks all LONGs (use SHORT direction)",
                "penalty": 0,
                "gate": "crash_long_block",
            }
        # SHORT in CRASH — check if strategy is allowed
        allowed = STRATEGY_REGIME_MAP.get(strategy)
        if allowed and "CRASH" not in allowed:
            return {
                "valid": False,
                "reason": f"{strategy} not valid in CRASH (even for SHORTs)",
                "penalty": 0,
                "gate": "crash_strategy_block",
            }

    # 2. Strategy-specific regime check
    allowed = STRATEGY_REGIME_MAP.get(strategy)
    if allowed and regime not in allowed:
        return {
            "valid": False,
            "reason": f"{strategy} not valid in {regime} (allowed: {', '.join(sorted(allowed))})",
            "penalty": 0,
            "gate": "invalid_regime_for_strategy",
        }

    # 3. Soft penalties
    combo = (strategy, regime)
    if combo in SOFT_PENALTY_COMBOS:
        result["penalty"] = SOFT_PENALTY_COMBOS[combo]
        result["gate"] = "soft_regime_penalty"

    # 4. Production mode is stricter
    if mode == "PRODUCTION":
        # In production, v9 in RANGE is blocked, not just penalized
        if strategy == "v9_breakout" and regime == "RANGE":
            return {
                "valid": False,
                "reason": "v9_breakout blocked in RANGE in production mode",
                "penalty": 0,
                "gate": "production_regime_block",
            }

    return result


# ═══════════════════════════════════════════
# PATTERN SUPPRESSION
# ═══════════════════════════════════════════

# Suppression thresholds
SUPPRESS_TRUST_THRESHOLD = 0.30      # Suppress if mature trust below this
SUPPRESS_QUICK_STOP_COUNT = 3        # Suppress if 3+ quick stops in recent trades
SUPPRESS_RECENT_LOSS_STREAK = 4      # Suppress after 4 consecutive losses
SUPPRESS_EXPECTANCY_THRESHOLD = -0.25  # Suppress if rolling expectancy below -0.25R
SUPPRESS_EXPECTANCY_MIN_TRADES = 6   # Need at least 6 trades for expectancy suppression
SUPPRESS_CYCLES = 6                  # Suppress for 6 cycles (~60 min)
SUPPRESS_CYCLES_PRODUCTION = 12      # Longer suppression in production


def _get_redis():
    import redis
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def get_pattern_key(strategy: str, regime: str, asset_class: str) -> str:
    return f"{strategy}:{regime}:{asset_class}"


def check_pattern_suppression(strategy: str, regime: str, asset_class: str) -> dict:
    """Check if a pattern is currently suppressed.

    Returns:
      suppressed: bool
      reason: str
      cycles_remaining: int
      suppressed_at: str
    """
    r = _get_redis()
    if not r:
        return {"suppressed": False, "reason": "", "cycles_remaining": 0}

    key = f"bahamut:training:suppression:{get_pattern_key(strategy, regime, asset_class)}"
    try:
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            return {
                "suppressed": True,
                "reason": data.get("reason", ""),
                "cycles_remaining": data.get("cycles_remaining", 0),
                "suppressed_at": data.get("suppressed_at", ""),
            }
    except Exception:
        pass
    return {"suppressed": False, "reason": "", "cycles_remaining": 0}


def suppress_pattern(strategy: str, regime: str, asset_class: str,
                     reason: str, cycles: int = SUPPRESS_CYCLES):
    """Temporarily suppress a pattern."""
    r = _get_redis()
    if not r:
        return

    key = f"bahamut:training:suppression:{get_pattern_key(strategy, regime, asset_class)}"
    data = {
        "strategy": strategy, "regime": regime, "asset_class": asset_class,
        "reason": reason, "cycles_remaining": cycles,
        "suppressed_regime": regime,  # For regime-aware release
        "suppressed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r.set(key, json.dumps(data), ex=cycles * 600 + 120)  # TTL = cycles × 10min + buffer
        logger.info("pattern_suppressed",
                    pattern=get_pattern_key(strategy, regime, asset_class),
                    reason=reason, cycles=cycles)
    except Exception as e:
        logger.warning("pattern_suppress_failed", error=str(e))


def decrement_suppression_cycles():
    """Called once per training cycle to count down suppression timers."""
    r = _get_redis()
    if not r:
        return

    try:
        keys = r.keys("bahamut:training:suppression:*")
        for key in keys:
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            remaining = data.get("cycles_remaining", 0) - 1
            if remaining <= 0:
                r.delete(key)
                pkey = key.split("suppression:")[-1] if isinstance(key, str) else key.decode().split("suppression:")[-1]
                logger.info("pattern_suppression_expired", pattern=pkey)
            else:
                data["cycles_remaining"] = remaining
                r.set(key, json.dumps(data), ex=remaining * 600 + 120)
    except Exception as e:
        logger.warning("suppression_decrement_failed", error=str(e))


def check_regime_release(current_regimes: dict[str, str]):
    """Release suppressions when regime changes.

    current_regimes: dict of asset_class → current regime
    e.g. {"crypto": "TREND", "stock": "RANGE"}

    If a pattern was suppressed in RANGE and the regime is now TREND,
    the suppression is lifted immediately.
    """
    r = _get_redis()
    if not r or not current_regimes:
        return

    try:
        keys = r.keys("bahamut:training:suppression:*")
        for key in keys:
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            suppressed_regime = data.get("suppressed_regime", "")
            asset_class = data.get("asset_class", "")

            if not suppressed_regime or not asset_class:
                continue

            # Check if regime has changed for this asset class
            current = current_regimes.get(asset_class, "")
            if current and current != suppressed_regime:
                pkey = key.split("suppression:")[-1] if isinstance(key, str) else key.decode().split("suppression:")[-1]
                r.delete(key)
                logger.info("pattern_unsuppressed",
                            pattern=pkey,
                            reason=f"regime_change: {suppressed_regime} → {current}",
                            old_regime=suppressed_regime,
                            new_regime=current)
    except Exception as e:
        logger.warning("regime_release_failed", error=str(e))


def evaluate_for_suppression(strategy: str, regime: str, asset_class: str,
                              mode: str = "TRAINING"):
    """Check if a pattern should be newly suppressed based on trust data.

    Called after trust update. If pattern meets suppression criteria,
    suppress it automatically.
    """
    try:
        from bahamut.training.learning_engine import get_pattern_trust
        trust = get_pattern_trust(strategy, regime, asset_class)

        maturity = trust.get("maturity", "provisional")
        if maturity == "provisional":
            return  # Never suppress provisional patterns

        blended = trust.get("blended_trust", 0.5)
        qs = trust.get("quick_stops", 0)
        total = trust.get("total_trades", 0)

        # Check recent outcomes for loss streak
        pattern_bucket = trust.get("buckets", {}).get("pattern", {})
        recent_qs = pattern_bucket.get("quick_stops", 0)

        cycles = SUPPRESS_CYCLES if mode == "TRAINING" else SUPPRESS_CYCLES_PRODUCTION

        # Rule 1: Mature + very low trust
        if maturity == "mature" and blended < SUPPRESS_TRUST_THRESHOLD:
            suppress_pattern(strategy, regime, asset_class,
                           f"Mature trust {blended:.2f} below {SUPPRESS_TRUST_THRESHOLD}", cycles)
            return

        # Rule 2: High quick-stop rate
        if total >= 5 and recent_qs >= SUPPRESS_QUICK_STOP_COUNT:
            suppress_pattern(strategy, regime, asset_class,
                           f"{recent_qs} quick stops in {total} trades", cycles)
            return

        # Rule 3: Developing + very bad trust
        if maturity == "developing" and blended < 0.25 and total >= 8:
            suppress_pattern(strategy, regime, asset_class,
                           f"Developing trust {blended:.2f} very low after {total} trades", cycles)
            return

        # Rule 4: Negative expectancy (NEW)
        expectancy = trust.get("expectancy", 0.0)
        if total >= SUPPRESS_EXPECTANCY_MIN_TRADES and expectancy < SUPPRESS_EXPECTANCY_THRESHOLD:
            suppress_pattern(strategy, regime, asset_class,
                           f"Negative expectancy {expectancy:.2f}R (threshold {SUPPRESS_EXPECTANCY_THRESHOLD}R) after {total} trades",
                           cycles)
            return

    except Exception as e:
        logger.debug("suppression_eval_failed", error=str(e))


def get_all_suppressions() -> list[dict]:
    """Get all currently suppressed patterns for dashboard."""
    r = _get_redis()
    if not r:
        return []

    result = []
    try:
        keys = r.keys("bahamut:training:suppression:*")
        for key in keys:
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                data["pattern_key"] = key.split("suppression:")[-1] if isinstance(key, str) else key.decode().split("suppression:")[-1]
                result.append(data)
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════
# COMBINED PRE-SCORING GATE
# ═══════════════════════════════════════════

def pre_score_gate(strategy: str, regime: str, asset_class: str,
                   direction: str = "LONG", mode: str = "TRAINING") -> dict:
    """Combined context gate + pattern suppression check.

    Call BEFORE priority scoring. Returns:
      allowed: bool
      reason: str
      gate: str (which gate blocked)
      penalty: int (soft penalty if allowed)
    """
    # 1. Context validation
    ctx = validate_strategy_context(strategy, regime, direction, mode)
    if not ctx["valid"]:
        return {
            "allowed": False,
            "reason": ctx["reason"],
            "gate": ctx["gate"],
            "penalty": 0,
        }

    # 2. Pattern suppression
    sup = check_pattern_suppression(strategy, regime, asset_class)
    if sup["suppressed"]:
        return {
            "allowed": False,
            "reason": f"Pattern suppressed: {sup['reason']} ({sup['cycles_remaining']} cycles remaining)",
            "gate": "suppressed_pattern",
            "penalty": 0,
        }

    # 3. Allowed (possibly with soft penalty)
    return {
        "allowed": True,
        "reason": "",
        "gate": ctx.get("gate", ""),
        "penalty": ctx.get("penalty", 0),
    }
