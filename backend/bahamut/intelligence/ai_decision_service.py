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
    """Get AI decision for a candidate. Derived deterministically — no API calls.

    Phase 4 Item 11: ai_source is one of:
      'fresh'          — fresh Opus posture (<60s old)
      'stale'          — stale Opus posture (60s-5min old; Opus call failed
                         on last try, using last good)
      'fallback_rules' — no Opus cache; derived from sentiment rules
      'disabled'       — No AI API keys set (DEEPSEEK/GEMINI); pure rules

    Downstream selector can elect to degrade gracefully when ai_source is
    stale or fallback_rules (e.g. soften penalties, widen thresholds).
    """
    start = time.time()

    # Layer A: get global posture + explicit source classification
    posture = "SELECTIVE"
    class_mode = "NORMAL"
    global_mult = 1.0
    dirs_allowed = True
    reason = ""
    ai_source = "fallback_rules"
    ai_cache_age = None  # seconds since posture was computed

    try:
        from bahamut.intelligence.ai_market_analyst import (
            get_analysis_source, _analysis_cache_ts, _stale_cache_ts,
        )
        opus, source_cat = get_analysis_source()
        ai_source = source_cat
        if opus:
            posture = opus.get("posture", "SELECTIVE")
            reason = opus.get("reason", "")[:100]
            # Compute cache age for downstream visibility
            import time as _t
            ref_ts = _analysis_cache_ts or _stale_cache_ts
            if ref_ts > 0:
                ai_cache_age = round(_t.time() - ref_ts, 1)

            if asset_class == "crypto":
                class_mode = opus.get("crypto_mode", "NORMAL")
                if direction == "LONG" and not opus.get("crypto_longs_allowed", True):
                    if class_mode == "CAUTION":
                        # CAUTION = trade smaller, not "don't trade"
                        global_mult *= 0.5
                        logger.info("ai_caution_size_reduction",
                                    asset=asset, direction="LONG",
                                    class_mode="CAUTION", size_mult=round(global_mult, 2))
                    else:
                        dirs_allowed = False
                if direction == "SHORT" and not opus.get("crypto_shorts_allowed", True):
                    if class_mode == "CAUTION":
                        global_mult *= 0.5
                        logger.info("ai_caution_size_reduction",
                                    asset=asset, direction="SHORT",
                                    class_mode="CAUTION", size_mult=round(global_mult, 2))
                    else:
                        dirs_allowed = False
            elif asset_class == "stock":
                class_mode = opus.get("stocks_mode", "NORMAL")
                if direction == "LONG" and not opus.get("stock_longs_allowed", True):
                    if class_mode == "CAUTION":
                        global_mult *= 0.5
                        logger.info("ai_caution_size_reduction",
                                    asset=asset, direction="LONG",
                                    class_mode="CAUTION", size_mult=round(global_mult, 2))
                    else:
                        dirs_allowed = False
                if direction == "SHORT" and not opus.get("stock_shorts_allowed", True):
                    if class_mode == "CAUTION":
                        global_mult *= 0.5
                        logger.info("ai_caution_size_reduction",
                                    asset=asset, direction="SHORT",
                                    class_mode="CAUTION", size_mult=round(global_mult, 2))
                    else:
                        dirs_allowed = False
            global_mult = _clamp(float(opus.get("global_size_multiplier", 1.0)), 0.25, 1.0)
    except Exception:
        ai_source = "fallback_rules"

    # If no Opus (fallback or disabled), derive from sentiment rules
    if ai_source in ("fallback_rules", "disabled"):
        try:
            from bahamut.intelligence.market_intelligence import get_pipeline_directives
            d = get_pipeline_directives()
            posture = d.get("posture", "SELECTIVE")
            global_mult = _clamp(d.get("global_size_multiplier", 1.0), 0.25, 1.0)
            if asset_class == "crypto":
                if not d.get("crypto_longs_allowed", True) and direction == "LONG":
                    # Fallback rules: crypto_longs_allowed=False means Fear regime.
                    # CAUTION = reduce size, not block.
                    global_mult *= 0.5
                    logger.info("ai_caution_size_reduction",
                                asset=asset, direction="LONG",
                                class_mode="CAUTION", size_mult=round(global_mult, 2),
                                source="fallback_rules")
                class_mode = "CAUTION" if not d.get("crypto_longs_allowed", True) else "NORMAL"
            reason = f"rules:{posture}"
        except Exception:
            pass

    # Phase 4 Item 11: stale/fallback/disabled → soften penalties by half
    # so a 4-minute-old cached DEFENSIVE posture doesn't keep blocking
    # trades that live data might unblock.
    posture_pen = {"AGGRESSIVE": 0, "SELECTIVE": -1, "DEFENSIVE": -3, "FROZEN": -4}
    mode_pen = {"NORMAL": 0, "CAUTION": -1, "RESTRICTED": -2, "FROZEN": -4}
    penalty = max(-4, posture_pen.get(posture, 0) + mode_pen.get(class_mode, 0))
    posture_mult = {"AGGRESSIVE": 1.0, "SELECTIVE": 0.95, "DEFENSIVE": 0.75, "FROZEN": 0.25}
    size_mult = _clamp(round(posture_mult.get(posture, 0.95) * global_mult, 2), 0.25, 1.0)

    # Track whether we softened (for diagnostics)
    softened = False
    if ai_source in ("stale", "fallback_rules", "disabled") and penalty < 0:
        # Halve penalty magnitude — don't let degraded data drive harsh blocks
        softened_penalty = max(penalty, int(penalty / 2))  # e.g. -4 → -2
        if softened_penalty != penalty:
            softened = True
            penalty = softened_penalty

    # System override
    if system_allowed_directions is not None:
        if direction not in system_allowed_directions:
            dirs_allowed = False

    latency = round((time.time() - start) * 1000, 1)

    # Map ai_source to the legacy _source string for existing callers
    legacy_source_map = {
        "fresh": "deepseek/gemini",
        "stale": "deepseek/gemini-stale",
        "fallback_rules": "rule-based",
        "disabled": "rule-based-disabled",
    }
    legacy_source = legacy_source_map.get(ai_source, "rule-based")

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
        "_source": legacy_source,
        # Phase 4 Item 11: canonical source + cache age + softening flag
        "ai_source": ai_source,
        "ai_cache_age_seconds": ai_cache_age,
        "ai_posture_softened": softened,
        "_fallback_used": ai_source in ("fallback_rules", "disabled"),
        "_latency_ms": latency,
        "_class_mode": class_mode,
    }

    logger.info("ai_decision_evaluated",
                asset=asset, strategy=strategy, direction=direction,
                posture=posture, class_mode=class_mode,
                allowed=decision["asset_decision"]["allowed"],
                penalty=penalty, size_mult=size_mult,
                source=legacy_source, ai_source=ai_source,
                cache_age=ai_cache_age, softened=softened,
                latency_ms=latency)
    return decision
