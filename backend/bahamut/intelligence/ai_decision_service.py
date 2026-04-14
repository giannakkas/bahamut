"""
AI Decision Service — Layer B: deterministic per-candidate shaping.

Derives asset-level decisions from:
  - Global AI posture (Layer A / Opus cached)
  - Adaptive news state
  - Sentiment gate
  - Hard risk rules

Does NOT call Opus per candidate. Zero latency risk.

Guardrails (NON-NEGOTIABLE):
  - confidence: 0 → 1
  - threshold_penalty: -4 → 0 (max -4 from global posture)
  - size_multiplier: 0.25 → 1.0
  - system direction overrides always win
"""
import time
import structlog

logger = structlog.get_logger()

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def get_ai_decision(
    asset: str, asset_class: str, strategy: str, direction: str,
    priority_score: float = 0, system_allowed_directions: list | None = None,
) -> dict:
    """Get AI decision for a candidate. Derived deterministically — no API calls."""
    start = time.time()

    # Layer A: get global posture from cached Opus (or rule-based fallback)
    posture = "SELECTIVE"
    class_mode = "NORMAL"
    global_mult = 1.0
    dirs_allowed = True
    source = "rule-based"
    reason = ""

    try:
        from bahamut.intelligence.ai_market_analyst import get_cached_analysis
        opus = get_cached_analysis()
        if opus:
            posture = opus.get("posture", "SELECTIVE")
            source = "opus-4.6"
            reason = opus.get("reason", "")[:100]
            if asset_class == "crypto":
                class_mode = opus.get("crypto_mode", "NORMAL")
                if direction == "LONG" and not opus.get("crypto_longs_allowed", True):
                    dirs_allowed = False
                if direction == "SHORT" and not opus.get("crypto_shorts_allowed", True):
                    dirs_allowed = False
            elif asset_class == "stock":
                class_mode = opus.get("stocks_mode", "NORMAL")
                if direction == "LONG" and not opus.get("stock_longs_allowed", True):
                    dirs_allowed = False
                if direction == "SHORT" and not opus.get("stock_shorts_allowed", True):
                    dirs_allowed = False
            global_mult = _clamp(float(opus.get("global_size_multiplier", 1.0)), 0.25, 1.0)
    except Exception:
        pass

    # If no Opus, derive from sentiment
    if source == "rule-based":
        try:
            from bahamut.intelligence.market_intelligence import get_pipeline_directives
            d = get_pipeline_directives()
            posture = d.get("posture", "SELECTIVE")
            global_mult = _clamp(d.get("global_size_multiplier", 1.0), 0.25, 1.0)
            if asset_class == "crypto":
                if not d.get("crypto_longs_allowed", True) and direction == "LONG":
                    dirs_allowed = False
                class_mode = "CAUTION" if not d.get("crypto_longs_allowed", True) else "NORMAL"
            reason = f"rules:{posture}"
        except Exception:
            pass

    # Derive penalty from posture + class mode (max -4)
    posture_pen = {"AGGRESSIVE": 0, "SELECTIVE": -1, "DEFENSIVE": -3, "FROZEN": -4}
    mode_pen = {"NORMAL": 0, "CAUTION": -1, "RESTRICTED": -2, "FROZEN": -4}
    penalty = max(-4, posture_pen.get(posture, 0) + mode_pen.get(class_mode, 0))

    # Derive size mult from posture
    posture_mult = {"AGGRESSIVE": 1.0, "SELECTIVE": 0.95, "DEFENSIVE": 0.75, "FROZEN": 0.25}
    size_mult = _clamp(round(posture_mult.get(posture, 0.95) * global_mult, 2), 0.25, 1.0)

    # System override
    if system_allowed_directions is not None:
        if direction not in system_allowed_directions:
            dirs_allowed = False

    latency = round((time.time() - start) * 1000, 1)

    decision = {
        "posture": posture,
        "asset_decision": {
            "allowed": dirs_allowed and class_mode != "FROZEN",
            "allowed_directions": ["LONG", "SHORT"] if dirs_allowed else [],
            "bias": "NEUTRAL",
            "confidence": 0,
            "threshold_penalty": penalty,
            "size_multiplier": size_mult,
            "reason": reason,
        },
        "global_adjustments": {
            "size_multiplier": global_mult,
            "risk_mode": "REDUCED" if posture in ("DEFENSIVE", "FROZEN") else "NORMAL",
        },
        "_source": source,
        "_fallback_used": source == "rule-based",
        "_latency_ms": latency,
        "_class_mode": class_mode,
    }

    logger.info("ai_decision_evaluated",
                asset=asset, strategy=strategy, direction=direction,
                posture=posture, class_mode=class_mode,
                allowed=decision["asset_decision"]["allowed"],
                penalty=penalty, size_mult=size_mult,
                source=source, latency_ms=latency)
    return decision
