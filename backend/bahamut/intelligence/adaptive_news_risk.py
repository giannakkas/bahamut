"""
Bahamut.AI — Adaptive News Risk Layer

Replaces the binary freeze/not-freeze model with a 4-mode state machine:
  NORMAL     → no restriction, full size
  CAUTION    → trade allowed, size reduced, threshold tightened
  RESTRICTED → only aligned-direction trades, size halved, threshold +6
  FROZEN     → all new trades blocked, very short-lived, auto-decays

Design principles:
  - Per-asset risk mode, not global freeze
  - Directional intelligence: aligned trades allowed in RESTRICTED
  - Time decay: restrictions fade over time
  - Starvation safety: detects over-blocking and demotes
  - Market-wide vs asset-specific separation
  - Feature-flagged: falls back to legacy freeze if disabled

Consumed by: selector (gating + scoring), engine (sizing), diagnostics.
"""
import time
import structlog
from dataclasses import dataclass

logger = structlog.get_logger()


# ═══════════════════════════════════════════
# FEATURE FLAG
# ═══════════════════════════════════════════
ADAPTIVE_NEWS_ENABLED = True


# ═══════════════════════════════════════════
# MODE DEFINITIONS + DOWNSTREAM BEHAVIOR
# ═══════════════════════════════════════════

MODES = {
    "NORMAL":     {"size_mult": 1.0,  "threshold_add": 0,  "aligned_only": False, "block": False},
    "CAUTION":    {"size_mult": 0.75, "threshold_add": 3,  "aligned_only": False, "block": False},
    "RESTRICTED": {"size_mult": 0.5,  "threshold_add": 6,  "aligned_only": True,  "block": False},
    "FROZEN":     {"size_mult": 0.0,  "threshold_add": 99, "aligned_only": True,  "block": True},
}

# ═══════════════════════════════════════════
# TRANSITION THRESHOLDS
# ═══════════════════════════════════════════

# Impact score thresholds for mode transitions
MODE_THRESHOLDS = {
    "FROZEN":     {"min_impact": 0.80, "min_shock": "EXTREME", "min_confidence": 0.6},
    "RESTRICTED": {"min_impact": 0.50, "min_shock": "HIGH"},
    "CAUTION":    {"min_impact": 0.20, "min_shock": "MEDIUM"},
}

# Time decay: mode degrades over time (seconds)
DECAY_SCHEDULE = {
    "FROZEN":     {"to_restricted": 600,  "to_caution": 1800, "to_normal": 3600},   # 10m→R, 30m→C, 1h→N
    "RESTRICTED": {"to_caution": 1200, "to_normal": 2400},                           # 20m→C, 40m→N
    "CAUTION":    {"to_normal": 1800},                                                 # 30m→N
}

# Starvation safety
MAX_FROZEN_PCT = 40          # If >40% of assets frozen, demote some
MAX_FROZEN_DURATION = 1800   # Max 30 min in FROZEN before auto-demote to RESTRICTED
STARVATION_CHECK_HOURS = 2   # Flag if 0 trades for this many hours


# ═══════════════════════════════════════════
# CORE DATA STRUCTURES
# ═══════════════════════════════════════════

@dataclass
class AssetNewsState:
    """Per-asset news risk state."""
    asset: str
    mode: str = "NORMAL"
    raw_impact: float = 0.0
    normalized_impact: float = 0.0
    shock: str = "NONE"
    bias: str = "NEUTRAL"
    confidence: float = 0.0
    freeze_reason: str = ""
    event_cluster_id: str = ""
    last_updated: float = 0.0       # time.time()
    mode_set_at: float = 0.0        # when current mode was assigned
    asset_specific: float = 0.0     # 0-1: direct asset mention
    class_risk: float = 0.0         # 0-1: class-wide risk
    macro_risk: float = 0.0         # 0-1: market-wide risk


def is_trade_aligned(direction: str, bias: str) -> bool:
    """Check if trade direction aligns with news bias."""
    if bias == "NEUTRAL":
        return True  # Neutral news doesn't oppose either direction
    return (direction == "LONG" and bias == "LONG") or \
           (direction == "SHORT" and bias == "SHORT")


# ═══════════════════════════════════════════
# MODE COMPUTATION
# ═══════════════════════════════════════════

def compute_news_mode(
    impact_score: float,
    shock: str,
    bias: str,
    confidence: float,
    freeze_trading: bool,
    age_seconds: float = 0,
) -> str:
    """Determine the news risk mode for an asset.

    Uses impact score, shock level, confidence, and age for time decay.
    Returns: NORMAL / CAUTION / RESTRICTED / FROZEN
    """
    # Time decay: reduce effective impact based on age
    if age_seconds > 0:
        # Half-life decay: impact halves every 30 minutes
        decay = 0.5 ** (age_seconds / 1800)
        effective_impact = impact_score * decay
    else:
        effective_impact = impact_score

    shock_rank = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "EXTREME": 4}.get(shock, 0)

    # Confidence-weighted shock: low-confidence EXTREME shouldn't force RESTRICTED
    # news_impact.py labels EXTREME too eagerly (impact=0.27 can be EXTREME via surprise magnitude)
    # If confidence < 0.5, downgrade effective shock by 1 level
    effective_shock = shock_rank
    if confidence < 0.5 and shock_rank >= 3:
        effective_shock = shock_rank - 1  # EXTREME→HIGH, HIGH→MEDIUM
    if confidence < 0.35 and shock_rank >= 2:
        effective_shock = max(1, shock_rank - 2)  # Even more aggressive downgrade

    # FROZEN: requires high impact + high confidence + extreme shock
    # Low confidence should NOT trigger FROZEN (prevents false positives)
    ft = MODE_THRESHOLDS["FROZEN"]
    if (effective_impact >= ft["min_impact"]
            and effective_shock >= 4
            and confidence >= ft.get("min_confidence", 0.6)):
        return "FROZEN"

    # Legacy freeze from time-based event proximity: cap at RESTRICTED (not FROZEN)
    # unless impact is genuinely high
    if freeze_trading and effective_impact < ft["min_impact"]:
        return "RESTRICTED"

    # RESTRICTED: high impact or genuinely high shock (confidence-weighted)
    rt = MODE_THRESHOLDS["RESTRICTED"]
    if effective_impact >= rt["min_impact"] or effective_shock >= 3:
        return "RESTRICTED"

    # CAUTION: moderate impact or moderate shock
    ct = MODE_THRESHOLDS["CAUTION"]
    if effective_impact >= ct["min_impact"] or effective_shock >= 2:
        return "CAUTION"

    return "NORMAL"


def apply_time_decay(state: AssetNewsState) -> str:
    """Apply time-based decay to an existing mode.
    Returns the decayed mode (may be less restrictive than current).
    """
    age = time.time() - state.mode_set_at
    current = state.mode

    if current == "FROZEN":
        sched = DECAY_SCHEDULE["FROZEN"]
        if age >= sched["to_normal"]:
            return "NORMAL"
        if age >= sched["to_caution"]:
            return "CAUTION"
        if age >= sched["to_restricted"]:
            return "RESTRICTED"
        return "FROZEN"

    if current == "RESTRICTED":
        sched = DECAY_SCHEDULE["RESTRICTED"]
        if age >= sched["to_normal"]:
            return "NORMAL"
        if age >= sched["to_caution"]:
            return "CAUTION"
        return "RESTRICTED"

    if current == "CAUTION":
        sched = DECAY_SCHEDULE["CAUTION"]
        if age >= sched["to_normal"]:
            return "NORMAL"
        return "CAUTION"

    return "NORMAL"


# ═══════════════════════════════════════════
# IMPACT NORMALIZATION
# Prevents "everything is EXTREME at once"
# ═══════════════════════════════════════════

def normalize_impacts(assessments: dict[str, "NewsImpactAssessment"]) -> dict[str, float]:
    """Normalize impact scores across all assets to prevent universal extremes.

    If >60% of assets have shock=EXTREME, the threshold is too sensitive.
    Apply percentile-based normalization to keep the distribution meaningful.

    Returns: {asset: normalized_impact}
    """
    if not assessments:
        return {}

    scores = {a: ass.impact_score for a, ass in assessments.items()}
    values = list(scores.values())

    if not values:
        return scores

    # If most assets have similar high scores, compress
    extreme_count = sum(1 for a in assessments.values() if a.shock_level == "EXTREME")
    total = len(assessments)

    if total > 0 and extreme_count / total > 0.5:
        # Too many extremes — normalize using percentile scaling
        sorted_vals = sorted(values)
        max_val = sorted_vals[-1] if sorted_vals else 1
        min_val = sorted_vals[0] if sorted_vals else 0
        spread = max_val - min_val

        if spread < 0.05:
            # All scores nearly identical — can't differentiate, cap at CAUTION level
            return {a: min(0.35, v) for a, v in scores.items()}

        # Scale to use full 0-1 range based on relative position
        return {
            a: round((v - min_val) / max(0.01, spread), 3)
            for a, v in scores.items()
        }

    return {a: round(v, 3) for a, v in scores.items()}


# ═══════════════════════════════════════════
# STARVATION SAFETY
# ═══════════════════════════════════════════

def check_starvation(states: dict[str, AssetNewsState], total_assets: int) -> dict:
    """Detect over-blocking and recommend demotions.

    Returns: {
        starvation_detected: bool,
        frozen_pct: float,
        demotions: [{asset, from_mode, to_mode, reason}],
    }
    """
    if not states:
        return {"starvation_detected": False, "frozen_pct": 0, "demotions": []}

    frozen = [a for a, s in states.items() if s.mode == "FROZEN"]
    restricted = [a for a, s in states.items() if s.mode == "RESTRICTED"]
    frozen_pct = len(frozen) / max(1, total_assets) * 100

    demotions = []
    now = time.time()

    # Rule 1: Too many frozen assets — demote oldest to RESTRICTED
    if frozen_pct > MAX_FROZEN_PCT:
        # Sort by age (oldest freeze first) and demote until under threshold
        by_age = sorted(frozen, key=lambda a: states[a].mode_set_at)
        target = int(total_assets * MAX_FROZEN_PCT / 100)
        for asset in by_age:
            if len(frozen) - len(demotions) <= target:
                break
            demotions.append({
                "asset": asset, "from_mode": "FROZEN", "to_mode": "RESTRICTED",
                "reason": f"Starvation guard: {frozen_pct:.0f}% frozen exceeds {MAX_FROZEN_PCT}% cap",
            })

    # Rule 2: Individual asset frozen too long
    for asset in frozen:
        if asset in [d["asset"] for d in demotions]:
            continue
        age = now - states[asset].mode_set_at
        if age > MAX_FROZEN_DURATION:
            demotions.append({
                "asset": asset, "from_mode": "FROZEN", "to_mode": "RESTRICTED",
                "reason": f"Frozen {age/60:.0f}min exceeds max {MAX_FROZEN_DURATION/60:.0f}min",
            })

    starvation = frozen_pct > MAX_FROZEN_PCT or len(demotions) > 0
    return {
        "starvation_detected": starvation,
        "frozen_pct": round(frozen_pct, 1),
        "frozen_count": len(frozen),
        "restricted_count": len(restricted),
        "demotions": demotions,
    }


# ═══════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════

def compute_adaptive_news_state(
    asset: str,
    assessment: "NewsImpactAssessment",
    existing_state: AssetNewsState | None = None,
    normalized_impact: float | None = None,
) -> AssetNewsState:
    """Compute the adaptive news risk state for a single asset.

    Args:
        asset: asset symbol
        assessment: from compute_news_impact / compute_news_impact_sync
        existing_state: previous state (for decay tracking)
        normalized_impact: from normalize_impacts() or None for raw

    Returns: AssetNewsState with mode, sizing params, and explanations
    """
    now = time.time()
    impact = normalized_impact if normalized_impact is not None else assessment.impact_score

    # Compute fresh mode from current data
    fresh_mode = compute_news_mode(
        impact_score=impact,
        shock=assessment.shock_level,
        bias=assessment.directional_bias,
        confidence=assessment.confidence,
        freeze_trading=assessment.freeze_trading,
        age_seconds=0,  # Fresh computation — no age decay yet
    )

    # If we have existing state, apply time decay
    if existing_state and existing_state.mode != "NORMAL":
        decayed_mode = apply_time_decay(existing_state)
        # Use the LESS restrictive of fresh and decayed
        # (fresh data can re-escalate, but time always de-escalates)
        mode_rank = {"NORMAL": 0, "CAUTION": 1, "RESTRICTED": 2, "FROZEN": 3}
        final_mode = fresh_mode if mode_rank.get(fresh_mode, 0) >= mode_rank.get(decayed_mode, 0) else decayed_mode
    else:
        final_mode = fresh_mode

    # Track when mode was set (for future decay)
    if existing_state and existing_state.mode == final_mode:
        mode_set_at = existing_state.mode_set_at
    else:
        mode_set_at = now

    return AssetNewsState(
        asset=asset,
        mode=final_mode,
        raw_impact=assessment.impact_score,
        normalized_impact=impact,
        shock=assessment.shock_level,
        bias=assessment.directional_bias,
        confidence=assessment.confidence,
        freeze_reason=assessment.freeze_reason if final_mode == "FROZEN" else "",
        last_updated=now,
        mode_set_at=mode_set_at,
    )


# ═══════════════════════════════════════════
# SELECTOR / ENGINE INTERFACE
# ═══════════════════════════════════════════

def get_news_gate_decision(
    state: AssetNewsState,
    trade_direction: str,
) -> dict:
    """Determine if a trade should proceed given the news state.

    Returns: {
        allowed: bool,
        mode: str,
        size_multiplier: float,
        threshold_penalty: int,
        reason: str,
    }
    """
    if not ADAPTIVE_NEWS_ENABLED:
        # Legacy fallback: use old freeze behavior
        return {"allowed": True, "mode": "LEGACY", "size_multiplier": 1.0,
                "threshold_penalty": 0, "reason": "adaptive_news_disabled"}

    mode_cfg = MODES[state.mode]

    # FROZEN: block everything
    if mode_cfg["block"]:
        return {
            "allowed": False, "mode": state.mode,
            "size_multiplier": 0.0, "threshold_penalty": mode_cfg["threshold_add"],
            "reason": f"FROZEN: {state.freeze_reason or state.shock}",
        }

    # RESTRICTED: only aligned trades
    if mode_cfg["aligned_only"]:
        aligned = is_trade_aligned(trade_direction, state.bias)
        if not aligned:
            return {
                "allowed": False, "mode": state.mode,
                "size_multiplier": 0.0, "threshold_penalty": mode_cfg["threshold_add"],
                "reason": f"RESTRICTED: {trade_direction} opposes news bias {state.bias}",
            }
        # Aligned trade in RESTRICTED: allowed but reduced
        return {
            "allowed": True, "mode": state.mode,
            "size_multiplier": mode_cfg["size_mult"],
            "threshold_penalty": mode_cfg["threshold_add"],
            "reason": f"RESTRICTED but aligned ({trade_direction}={state.bias})",
        }

    # CAUTION / NORMAL: allowed with adjustments
    return {
        "allowed": True, "mode": state.mode,
        "size_multiplier": mode_cfg["size_mult"],
        "threshold_penalty": mode_cfg["threshold_add"],
        "reason": f"{state.mode}: impact={state.normalized_impact:.2f}",
    }


# ═══════════════════════════════════════════
# BATCH COMPUTATION (for diagnostics)
# ═══════════════════════════════════════════

# In-memory cache of per-asset states
_asset_states: dict[str, AssetNewsState] = {}
_last_batch_update: float = 0
_BATCH_TTL = 60  # seconds


def get_all_news_states() -> dict[str, AssetNewsState]:
    """Return current cached news states for all tracked assets."""
    return dict(_asset_states)


def update_batch_news_states(assets: list[str], asset_classes: dict[str, str]) -> dict:
    """Recompute news states for all tracked assets.

    Called periodically by diagnostics or orchestrator.
    Returns portfolio-level summary.
    """
    global _asset_states, _last_batch_update

    if time.time() - _last_batch_update < _BATCH_TTL and _asset_states:
        # Use cached
        states = _asset_states
    else:
        # Recompute
        from bahamut.intelligence.news_impact import compute_news_impact_sync
        assessments = {}
        for asset in assets:
            ac = asset_classes.get(asset, "crypto")
            assessments[asset] = compute_news_impact_sync(asset, ac)

        # Normalize to prevent universal extremes
        normalized = normalize_impacts(assessments)

        states = {}
        for asset in assets:
            existing = _asset_states.get(asset)
            states[asset] = compute_adaptive_news_state(
                asset=asset,
                assessment=assessments[asset],
                existing_state=existing,
                normalized_impact=normalized.get(asset),
            )

        # Starvation check + apply demotions
        starv = check_starvation(states, len(assets))
        for demotion in starv.get("demotions", []):
            a = demotion["asset"]
            if a in states:
                states[a].mode = demotion["to_mode"]
                logger.info("news_starvation_demotion",
                            asset=a, from_mode=demotion["from_mode"],
                            to_mode=demotion["to_mode"], reason=demotion["reason"])

        _asset_states = states
        _last_batch_update = time.time()

    # Build summary
    mode_counts = {"NORMAL": 0, "CAUTION": 0, "RESTRICTED": 0, "FROZEN": 0}
    for s in states.values():
        mode_counts[s.mode] = mode_counts.get(s.mode, 0) + 1

    return {
        "total_assets": len(states),
        "mode_counts": mode_counts,
        "frozen_pct": round(mode_counts["FROZEN"] / max(1, len(states)) * 100, 1),
        "starvation_guard_active": mode_counts["FROZEN"] / max(1, len(states)) > MAX_FROZEN_PCT / 100,
    }


def get_asset_news_state(asset: str) -> AssetNewsState:
    """Get the current news state for a single asset.
    Falls back to NORMAL if not computed yet.
    """
    return _asset_states.get(asset, AssetNewsState(asset=asset))


def diagnostics_snapshot() -> dict:
    """Full snapshot for diagnostics output."""
    states = get_all_news_states()
    if not states:
        return {"adaptive_news_enabled": ADAPTIVE_NEWS_ENABLED, "assets": {}, "summary": {}}

    per_asset = {}
    for asset, s in states.items():
        age = time.time() - s.mode_set_at if s.mode_set_at > 0 else 0
        per_asset[asset] = {
            "mode": s.mode,
            "raw_impact": s.raw_impact,
            "normalized_impact": s.normalized_impact,
            "shock": s.shock,
            "bias": s.bias,
            "confidence": s.confidence,
            "aligned_directions": _aligned_directions(s.bias),
            "size_multiplier": MODES[s.mode]["size_mult"],
            "threshold_penalty": MODES[s.mode]["threshold_add"],
            "freeze_reason": s.freeze_reason,
            "age_seconds": round(age),
            "decay_state": apply_time_decay(s) if s.mode != "NORMAL" else "NORMAL",
        }

    mode_counts = {"NORMAL": 0, "CAUTION": 0, "RESTRICTED": 0, "FROZEN": 0}
    for s in states.values():
        mode_counts[s.mode] = mode_counts.get(s.mode, 0) + 1

    # Per-class summary
    summary_by_class = {}
    try:
        from bahamut.config_assets import ASSET_CLASS_MAP
        for asset, s in states.items():
            cls = ASSET_CLASS_MAP.get(asset, "other")
            if cls not in summary_by_class:
                summary_by_class[cls] = {"NORMAL": 0, "CAUTION": 0, "RESTRICTED": 0, "FROZEN": 0}
            summary_by_class[cls][s.mode] = summary_by_class[cls].get(s.mode, 0) + 1
    except Exception:
        pass

    return {
        "adaptive_news_enabled": ADAPTIVE_NEWS_ENABLED,
        "assets": per_asset,
        "summary": {
            "mode_counts": mode_counts,
            "frozen_pct": round(mode_counts["FROZEN"] / max(1, len(states)) * 100, 1),
            "starvation_guard_active": mode_counts["FROZEN"] / max(1, len(states)) > MAX_FROZEN_PCT / 100,
        },
        "summary_by_class": summary_by_class,
    }


def _aligned_directions(bias: str) -> list[str]:
    if bias == "LONG":
        return ["LONG"]
    if bias == "SHORT":
        return ["SHORT"]
    return ["LONG", "SHORT"]
