"""
AI Decision Service — Opus 4.6 controlled decision layer with strict guardrails.

Architecture:
  1. Hard Rules (deterministic)         ← runs BEFORE this
  2. AI Decision Layer (this module)    ← Opus 4.6 advisory
  3. Validation & Clamping (this module) ← deterministic guardrails
  4. Selector & Execution              ← existing system

The AI CANNOT:
  - Execute trades directly
  - Override hard risk limits
  - Create new candidates (only influence existing ones)
  - Return unclamped values

The AI CAN:
  - Adjust threshold penalties (-10 to 0)
  - Adjust size multipliers (0.25 to 1.0)
  - Filter allowed directions
  - Provide bias and confidence
  - Explain reasoning
"""
import time
import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# STRICT OUTPUT SCHEMA
# ═══════════════════════════════════════════

_DEFAULT_DECISION = {
    "posture": "SELECTIVE",
    "asset_decision": {
        "allowed": True,
        "allowed_directions": ["LONG", "SHORT"],
        "bias": "NEUTRAL",
        "confidence": 0.0,
        "threshold_penalty": 0,
        "size_multiplier": 1.0,
        "reason": "no_ai_context",
    },
    "global_adjustments": {
        "size_multiplier": 1.0,
        "risk_mode": "NORMAL",
    },
    "_fallback_used": True,
    "_latency_ms": 0,
}

# ═══════════════════════════════════════════
# CLAMPING (NON-NEGOTIABLE)
# ═══════════════════════════════════════════

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp_decision(raw: dict) -> dict:
    """Apply hard guardrails to any AI output. No exceptions."""
    ad = raw.get("asset_decision", {})
    ga = raw.get("global_adjustments", {})

    # Clamp confidence: 0 → 1
    ad["confidence"] = round(_clamp(float(ad.get("confidence", 0)), 0.0, 1.0), 3)

    # Clamp threshold_penalty: 0 → -10 ONLY (must be ≤ 0)
    penalty = int(ad.get("threshold_penalty", 0))
    ad["threshold_penalty"] = max(-10, min(0, penalty))

    # Clamp size_multiplier: 0.25 → 1.0
    ad["size_multiplier"] = round(_clamp(float(ad.get("size_multiplier", 1.0)), 0.25, 1.0), 2)
    ga["size_multiplier"] = round(_clamp(float(ga.get("size_multiplier", 1.0)), 0.25, 1.0), 2)

    # Validate allowed_directions: must be subset of ["LONG", "SHORT"]
    valid_dirs = {"LONG", "SHORT"}
    dirs = ad.get("allowed_directions", ["LONG", "SHORT"])
    if not isinstance(dirs, list):
        dirs = ["LONG", "SHORT"]
    ad["allowed_directions"] = [d for d in dirs if d in valid_dirs] or ["LONG", "SHORT"]

    # Validate bias
    if ad.get("bias") not in ("LONG", "SHORT", "NEUTRAL"):
        ad["bias"] = "NEUTRAL"

    # Validate posture
    if raw.get("posture") not in ("AGGRESSIVE", "SELECTIVE", "DEFENSIVE", "FROZEN"):
        raw["posture"] = "SELECTIVE"

    # Validate risk_mode
    if ga.get("risk_mode") not in ("NORMAL", "REDUCED", "MINIMAL"):
        ga["risk_mode"] = "NORMAL"

    # Enforce allowed is boolean
    ad["allowed"] = bool(ad.get("allowed", True))

    # Truncate reason
    ad["reason"] = str(ad.get("reason", ""))[:200]

    raw["asset_decision"] = ad
    raw["global_adjustments"] = ga
    return raw


# ═══════════════════════════════════════════
# DECISION BUILDER (from cached Opus analysis)
# ═══════════════════════════════════════════

def get_ai_decision(
    asset: str,
    asset_class: str,
    strategy: str,
    direction: str,
    priority_score: float = 0,
    system_allowed_directions: list | None = None,
) -> dict:
    """
    Get AI decision for a specific candidate signal.

    Uses cached Opus market analysis + market intelligence snapshot.
    Does NOT make new API calls (zero latency risk).
    Returns clamped, validated decision.

    Args:
        asset: e.g. "BTCUSD"
        asset_class: e.g. "crypto"
        strategy: e.g. "v10_mean_reversion"
        direction: candidate's proposed direction "LONG" or "SHORT"
        priority_score: candidate's base priority score
        system_allowed_directions: directions allowed by hard rules (sentinel gate)
    """
    start = time.time()
    decision = None

    try:
        decision = _build_decision_from_opus(asset, asset_class, strategy, direction, priority_score)
    except Exception as e:
        logger.warning("ai_decision_build_error", asset=asset, error=str(e)[:100])

    if not decision:
        try:
            decision = _build_decision_from_rules(asset, asset_class, strategy, direction)
        except Exception:
            pass

    if not decision:
        decision = dict(_DEFAULT_DECISION)
        decision["_fallback_used"] = True

    # ── CLAMP (non-negotiable) ──
    decision = _clamp_decision(decision)

    # ── ENFORCE SYSTEM OVERRIDES (hard rules win) ──
    if system_allowed_directions is not None:
        # System bans a direction → override AI
        ai_dirs = set(decision["asset_decision"]["allowed_directions"])
        sys_dirs = set(system_allowed_directions)
        final_dirs = list(ai_dirs & sys_dirs)
        if not final_dirs:
            # System blocks all AI-allowed directions → block trade
            decision["asset_decision"]["allowed"] = False
            decision["asset_decision"]["reason"] = "system_direction_override"
        decision["asset_decision"]["allowed_directions"] = final_dirs or list(sys_dirs)

    # Check if candidate direction is allowed
    if direction not in decision["asset_decision"]["allowed_directions"]:
        decision["asset_decision"]["allowed"] = False
        if "direction_blocked" not in decision["asset_decision"].get("reason", ""):
            decision["asset_decision"]["reason"] += f" | direction_blocked:{direction}"

    latency = round((time.time() - start) * 1000, 1)
    decision["_latency_ms"] = latency

    # ── AUDIT LOG ──
    logger.info("ai_decision_evaluated",
                asset=asset, strategy=strategy, direction=direction,
                allowed=decision["asset_decision"]["allowed"],
                bias=decision["asset_decision"]["bias"],
                confidence=decision["asset_decision"]["confidence"],
                penalty=decision["asset_decision"]["threshold_penalty"],
                size_mult=decision["asset_decision"]["size_multiplier"],
                posture=decision.get("posture"),
                fallback=decision.get("_fallback_used", False),
                latency_ms=latency)

    return decision


def _build_decision_from_opus(asset, asset_class, strategy, direction, priority_score) -> dict | None:
    """Build decision from cached Opus 4.6 analysis. No API calls."""
    from bahamut.intelligence.ai_market_analyst import get_cached_analysis
    opus = get_cached_analysis()
    if not opus:
        return None

    posture = opus.get("overall_posture", "SELECTIVE")
    class_analysis = opus.get("class_analysis", {}).get(asset_class, {})
    high_conviction = opus.get("high_conviction_calls", [])

    # Base from Opus class analysis
    ai_bias = class_analysis.get("bias", "NEUTRAL")
    ai_confidence = class_analysis.get("confidence", 0.5)
    ai_mode = class_analysis.get("mode", "NORMAL")

    # Check high conviction calls for this asset
    for call in high_conviction:
        if call.get("asset_or_class", "").upper() == asset.upper() or \
           call.get("asset_or_class", "").lower() == asset_class.lower():
            ai_bias = call.get("direction", ai_bias)
            ai_confidence = max(ai_confidence, call.get("confidence", 0))

    # Derive allowed directions from Opus analysis
    allowed_dirs = ["LONG", "SHORT"]
    if ai_mode == "FROZEN":
        allowed_dirs = []
    elif ai_mode == "RESTRICTED" and ai_bias == "SHORT":
        allowed_dirs = ["SHORT"]
    elif ai_mode == "RESTRICTED" and ai_bias == "LONG":
        allowed_dirs = ["LONG"]

    # Derive threshold penalty from mode
    penalty_map = {"NORMAL": 0, "CAUTION": -3, "RESTRICTED": -6, "FROZEN": -10}
    penalty = penalty_map.get(ai_mode, 0)

    # Derive size multiplier from posture + mode
    posture_mult = {"AGGRESSIVE": 1.0, "SELECTIVE": 0.9, "DEFENSIVE": 0.75, "FROZEN": 0.25}
    mode_mult = {"NORMAL": 1.0, "CAUTION": 0.85, "RESTRICTED": 0.6, "FROZEN": 0.25}
    size_mult = round(posture_mult.get(posture, 0.9) * mode_mult.get(ai_mode, 1.0), 2)

    # Global adjustments
    risk_mode = "NORMAL"
    if posture in ("DEFENSIVE", "FROZEN"):
        risk_mode = "REDUCED" if posture == "DEFENSIVE" else "MINIMAL"

    reason = class_analysis.get("reasoning", f"opus:{posture}/{ai_mode}/{ai_bias}")

    return {
        "posture": posture,
        "asset_decision": {
            "allowed": ai_mode != "FROZEN",
            "allowed_directions": allowed_dirs,
            "bias": ai_bias,
            "confidence": ai_confidence,
            "threshold_penalty": penalty,
            "size_multiplier": size_mult,
            "reason": reason,
        },
        "global_adjustments": {
            "size_multiplier": posture_mult.get(posture, 0.9),
            "risk_mode": risk_mode,
        },
        "_fallback_used": False,
        "_source": "opus-4.6",
    }


def _build_decision_from_rules(asset, asset_class, strategy, direction) -> dict | None:
    """Fallback: build decision from rule-based market intelligence."""
    from bahamut.intelligence.market_intelligence import get_ai_context_for_asset, get_pipeline_directives
    ctx = get_ai_context_for_asset(asset)
    directives = get_pipeline_directives()

    posture = directives.get("posture", "SELECTIVE")
    mode = ctx.get("ai_market_mode", "NORMAL")

    penalty_map = {"NORMAL": 0, "CAUTION": -3, "RESTRICTED": -6, "FROZEN": -10}
    mode_mult = {"NORMAL": 1.0, "CAUTION": 0.85, "RESTRICTED": 0.6, "FROZEN": 0.25}

    return {
        "posture": posture,
        "asset_decision": {
            "allowed": mode != "FROZEN",
            "allowed_directions": ctx.get("ai_allowed_directions", ["LONG", "SHORT"]),
            "bias": ctx.get("ai_bias", "NEUTRAL"),
            "confidence": ctx.get("ai_confidence", 0),
            "threshold_penalty": penalty_map.get(mode, 0),
            "size_multiplier": round(min(ctx.get("ai_size_mult", 1.0), mode_mult.get(mode, 1.0)), 2),
            "reason": ctx.get("ai_reason", f"rules:{posture}/{mode}"),
        },
        "global_adjustments": {
            "size_multiplier": directives.get("global_size_multiplier", 1.0),
            "risk_mode": "REDUCED" if posture == "DEFENSIVE" else "NORMAL",
        },
        "_fallback_used": True,
        "_source": "rule-based",
    }
