"""
Bahamut.AI Threshold Tuner — auto-adjusts consensus thresholds.

Reads meta-learning report + trade history. Tightens thresholds when
the system is losing, loosens when it's winning. Persists overrides
to DB so they survive restarts.

Safety: bounded adjustments (max ±0.08 per tuning cycle), floor/ceiling
on all thresholds, and revert-to-defaults on emergency calibration.
"""
import json
import structlog

logger = structlog.get_logger()

# Absolute bounds — thresholds can never go outside these
BOUNDS = {
    "strong_signal": (0.55, 0.95),
    "signal": (0.40, 0.85),
    "weak_signal": (0.30, 0.70),
    "min_confidence": (0.30, 0.75),
}
MAX_STEP = 0.08  # max adjustment per tuning cycle

# Baseline defaults (never mutated — used for reset)
BASELINE_THRESHOLDS = {
    "CONSERVATIVE": {"strong_signal": 0.82, "signal": 0.70, "weak_signal": 0.55, "min_agreement": 7, "min_confidence": 0.60},
    "BALANCED":     {"strong_signal": 0.72, "signal": 0.58, "weak_signal": 0.45, "min_agreement": 6, "min_confidence": 0.50},
    "AGGRESSIVE":   {"strong_signal": 0.62, "signal": 0.48, "weak_signal": 0.35, "min_agreement": 5, "min_confidence": 0.40},
}


def apply_threshold_tuning(report) -> dict:
    """
    Apply threshold adjustments based on SystemHealthReport AND stress assessment.
    Returns dict of changes made.
    """
    from bahamut.consensus.engine import PROFILE_THRESHOLDS

    changes = {}

    # Collect actions from meta-learning report
    all_actions = list(report.recommended_actions or [])

    # Also collect actions from stress assessment
    try:
        from bahamut.stress.assessment import get_stress_assessment
        sa = get_stress_assessment()
        if sa.has_recent_results:
            for a in sa.recommended_actions:
                if a.get("target") == "thresholds":
                    # Map stress actions to threshold tuner format
                    act = a.get("action", "")
                    if act == "TIGHTEN":
                        all_actions.append({"action": "TIGHTEN_THRESHOLDS",
                                            "reason": f"[stress] {a.get('reason', '')}"})
                    elif act == "LOOSEN":
                        all_actions.append({"action": "LOOSEN_CANDIDATE",
                                            "reason": f"[stress] {a.get('reason', '')}"})
    except Exception:
        pass

    for action in all_actions:
        act = action.get("action", "")

        if act == "TIGHTEN_THRESHOLDS":
            for profile in PROFILE_THRESHOLDS:
                t = PROFILE_THRESHOLDS[profile]
                old = dict(t)
                step = min(MAX_STEP, 0.04)
                t["strong_signal"] = _clamp("strong_signal", t["strong_signal"] + step)
                t["signal"] = _clamp("signal", t["signal"] + step)
                t["weak_signal"] = _clamp("weak_signal", t["weak_signal"] + step * 0.5)
                t["min_confidence"] = _clamp("min_confidence", t["min_confidence"] + step * 0.5)
                changes[f"tighten_{profile}"] = {
                    k: {"old": round(old[k], 3), "new": round(t[k], 3)}
                    for k in ["strong_signal", "signal", "weak_signal", "min_confidence"]
                    if abs(old[k] - t[k]) > 0.001
                }
            logger.info("thresholds_tightened", reason=action.get("reason"))

        elif act == "LOOSEN_CANDIDATE":
            # Only loosen BALANCED and AGGRESSIVE, not CONSERVATIVE
            for profile in ["BALANCED", "AGGRESSIVE"]:
                t = PROFILE_THRESHOLDS[profile]
                old = dict(t)
                step = min(MAX_STEP, 0.03)
                t["strong_signal"] = _clamp("strong_signal", t["strong_signal"] - step)
                t["signal"] = _clamp("signal", t["signal"] - step)
                changes[f"loosen_{profile}"] = {
                    k: {"old": round(old[k], 3), "new": round(t[k], 3)}
                    for k in ["strong_signal", "signal"]
                    if abs(old[k] - t[k]) > 0.001
                }
            logger.info("thresholds_loosened", reason=action.get("reason"))

    if changes:
        _persist_thresholds(PROFILE_THRESHOLDS)

    return changes


def reset_to_defaults():
    """Reset all thresholds to baseline. Called by emergency calibration."""
    from bahamut.consensus.engine import PROFILE_THRESHOLDS
    import copy
    for profile, base in BASELINE_THRESHOLDS.items():
        PROFILE_THRESHOLDS[profile] = copy.deepcopy(base)
    logger.warning("thresholds_reset_to_defaults")
    _persist_thresholds(PROFILE_THRESHOLDS)


def load_persisted_thresholds():
    """Load threshold overrides from DB on startup."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        from bahamut.consensus.engine import PROFILE_THRESHOLDS
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT profile, thresholds FROM threshold_overrides
                ORDER BY updated_at DESC
            """))
            for row in r.mappings().all():
                profile = row["profile"]
                if profile in PROFILE_THRESHOLDS and row["thresholds"]:
                    stored = row["thresholds"] if isinstance(row["thresholds"], dict) else json.loads(row["thresholds"])
                    for k, v in stored.items():
                        if k in PROFILE_THRESHOLDS[profile] and isinstance(v, (int, float)):
                            PROFILE_THRESHOLDS[profile][k] = v
            logger.info("thresholds_loaded_from_db")
    except Exception as e:
        logger.debug("threshold_load_skipped", error=str(e))


def get_current_thresholds() -> dict:
    """Return current runtime thresholds (may differ from defaults)."""
    from bahamut.consensus.engine import PROFILE_THRESHOLDS
    return {p: dict(t) for p, t in PROFILE_THRESHOLDS.items()}


def _clamp(key: str, value: float) -> float:
    lo, hi = BOUNDS.get(key, (0.3, 0.95))
    return round(max(lo, min(hi, value)), 3)


def _persist_thresholds(thresholds: dict):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS threshold_overrides (
                    id SERIAL PRIMARY KEY, profile VARCHAR(30) UNIQUE,
                    thresholds JSONB, updated_at TIMESTAMP DEFAULT NOW())
            """))
            for profile, t in thresholds.items():
                conn.execute(text("""
                    INSERT INTO threshold_overrides (profile, thresholds, updated_at)
                    VALUES (:p, :t, NOW())
                    ON CONFLICT (profile) DO UPDATE SET thresholds = :t, updated_at = NOW()
                """), {"p": profile, "t": json.dumps(t)})
            conn.commit()
    except Exception as e:
        logger.warning("threshold_persist_failed", error=str(e))
