"""
Bahamut Training — Enhanced Learning Engine v2

Maturity-aware trust with sample-size weighting and trust decay.

Maturity tiers:
  provisional (0-4 samples)  → confidence_weight ~0.10-0.25
  developing  (5-14 samples) → confidence_weight ~0.30-0.60
  mature      (15+ samples)  → confidence_weight ~0.60-1.00

Sample-size-aware blending:
  Specific buckets only dominate when they have enough samples.
  Low-sample buckets fall back to broader trust.

Trust decay:
  Inactive buckets lose confidence (not value) over time.
  7 days idle → confidence starts fading. 30 days → floor of 0.30.
"""
import json
import os
import structlog
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

logger = structlog.get_logger()

# ── Maturity tiers ──
TIER_PROVISIONAL_MAX = 4
TIER_DEVELOPING_MAX = 14
CONFIDENCE_PROVISIONAL = 0.25
CONFIDENCE_DEVELOPING = 0.60
CONFIDENCE_MATURE = 1.00

# ── EMA ──
TRUST_EMA_ALPHA = 0.15
TRUST_DEFAULT = 0.50
QUICK_SL_BARS = 3

# ── Decay ──
DECAY_START_DAYS = 7
DECAY_FULL_DAYS = 30
DECAY_FLOOR = 0.30

# ── Blending base weights ──
BLEND_STRATEGY = 0.25
BLEND_REGIME = 0.30
BLEND_CLASS = 0.20
BLEND_PATTERN = 0.25

TRUST_TTL_SECONDS = 86400 * 60


def _get_redis():
    import redis
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


# ═══════════════════════════════════════════
# MATURITY HELPERS
# ═══════════════════════════════════════════

def get_maturity_state(samples: int) -> str:
    if samples <= TIER_PROVISIONAL_MAX:
        return "provisional"
    elif samples <= TIER_DEVELOPING_MAX:
        return "developing"
    return "mature"


def get_confidence_weight(samples: int) -> float:
    """Smooth confidence ramp: 0 samples → 0, 4 → 0.25, 14 → 0.60, 30+ → 1.0"""
    if samples <= 0:
        return 0.0
    if samples <= TIER_PROVISIONAL_MAX:
        return round(0.10 + (samples / TIER_PROVISIONAL_MAX) * (CONFIDENCE_PROVISIONAL - 0.10), 3)
    if samples <= TIER_DEVELOPING_MAX:
        progress = (samples - TIER_PROVISIONAL_MAX) / (TIER_DEVELOPING_MAX - TIER_PROVISIONAL_MAX)
        return round(CONFIDENCE_PROVISIONAL + progress * (CONFIDENCE_DEVELOPING - CONFIDENCE_PROVISIONAL), 3)
    progress = min(1.0, (samples - TIER_DEVELOPING_MAX) / 15)
    return round(CONFIDENCE_DEVELOPING + progress * (CONFIDENCE_MATURE - CONFIDENCE_DEVELOPING), 3)


def get_decay_factor(last_updated_iso: str) -> float:
    """Decay confidence (not value) for stale patterns. 1.0=fresh, 0.3=stale."""
    if not last_updated_iso:
        return DECAY_FLOOR
    try:
        last = datetime.fromisoformat(last_updated_iso.replace("Z", "+00:00"))
        days_idle = (datetime.now(timezone.utc) - last).total_seconds() / 86400
        if days_idle <= DECAY_START_DAYS:
            return 1.0
        if days_idle >= DECAY_FULL_DAYS:
            return DECAY_FLOOR
        progress = (days_idle - DECAY_START_DAYS) / (DECAY_FULL_DAYS - DECAY_START_DAYS)
        return round(1.0 - progress * (1.0 - DECAY_FLOOR), 3)
    except Exception:
        return 1.0


# ═══════════════════════════════════════════
# LEARNING CONTEXT
# ═══════════════════════════════════════════

@dataclass
class LearningContext:
    strategy: str
    asset: str
    asset_class: str
    direction: str
    regime: str
    exit_reason: str
    pnl: float
    r_multiple: float
    bars_held: int
    quick_stop: bool
    outcome_score: float


def compute_learning_context(trade_dict: dict) -> LearningContext:
    pnl = float(trade_dict.get("pnl", 0))
    risk = float(trade_dict.get("risk_amount", 0))
    bars = int(trade_dict.get("bars_held", 0))
    exit_reason = str(trade_dict.get("exit_reason", "")).upper()
    r_multiple = pnl / risk if risk > 0 else 0.0
    quick_stop = exit_reason == "SL" and bars <= QUICK_SL_BARS

    if exit_reason == "TP":
        score = min(1.0, 0.6 + r_multiple * 0.1)
    elif exit_reason == "SL":
        score = max(-1.0, -0.8 - abs(r_multiple) * 0.1) if quick_stop else max(-1.0, -0.4 - abs(r_multiple) * 0.1)
    elif exit_reason == "TIMEOUT":
        if pnl > 0:
            score = min(0.5, 0.1 + r_multiple * 0.2)
        elif abs(r_multiple) < 0.2:
            score = 0.0  # True scratch — economically neutral, don't penalize
        else:
            score = max(-0.5, -0.15 - abs(r_multiple) * 0.1)
    else:
        score = 0.0

    return LearningContext(
        strategy=str(trade_dict.get("strategy", "")),
        asset=str(trade_dict.get("asset", "")),
        asset_class=str(trade_dict.get("asset_class", "")),
        direction=str(trade_dict.get("direction", "")),
        regime=str(trade_dict.get("regime", "")),
        exit_reason=exit_reason, pnl=round(pnl, 2),
        r_multiple=round(r_multiple, 4), bars_held=bars,
        quick_stop=quick_stop, outcome_score=round(score, 4),
    )


# ═══════════════════════════════════════════
# TRUST UPDATE
# ═══════════════════════════════════════════

def _build_trust_keys(ctx: LearningContext) -> list[str]:
    return [
        f"bahamut:training:trust:strategy:{ctx.strategy}",
        f"bahamut:training:trust:strategy_regime:{ctx.strategy}:{ctx.regime}",
        f"bahamut:training:trust:strategy_class:{ctx.strategy}:{ctx.asset_class}",
        f"bahamut:training:trust:pattern:{ctx.strategy}:{ctx.regime}:{ctx.asset_class}",
    ]


def update_trust_from_trade(ctx: LearningContext):
    r = _get_redis()
    if not r:
        return

    now = datetime.now(timezone.utc).isoformat()

    for key in _build_trust_keys(ctx):
        try:
            raw = r.get(key)
            trust = json.loads(raw) if raw else {
                "trades": 0, "wins": 0, "losses": 0, "quick_stops": 0,
                "trust_score": TRUST_DEFAULT, "recent_outcomes": [], "last_updated": "",
            }

            trust["trades"] += 1
            if ctx.pnl > 0:
                trust["wins"] += 1
            elif ctx.pnl < -0.01:  # Only count real losses, not breakeven scratches
                trust["losses"] += 1
            if ctx.quick_stop:
                trust["quick_stops"] += 1

            recent = trust.get("recent_outcomes", [])
            recent.append(ctx.outcome_score)
            if len(recent) > 20:
                recent = recent[-20:]
            trust["recent_outcomes"] = recent

            # Store R-multiples for expectancy calculation
            r_mults = trust.get("recent_r_multiples", [])
            r_mults.append(ctx.r_multiple)
            if len(r_mults) > 20:
                r_mults = r_mults[-20:]
            trust["recent_r_multiples"] = r_mults

            samples = trust["trades"]
            maturity = get_maturity_state(samples)

            # Adaptive alpha: provisional = more reactive, mature = stable
            if maturity == "provisional":
                alpha = min(0.35, 0.5 / max(1, samples))
            elif maturity == "developing":
                alpha = TRUST_EMA_ALPHA * 1.2
            else:
                alpha = TRUST_EMA_ALPHA

            mapped = (ctx.outcome_score + 1) / 2
            old = trust["trust_score"]
            trust["trust_score"] = round(old * (1 - alpha) + mapped * alpha, 4)
            trust["maturity"] = maturity
            trust["confidence_weight"] = get_confidence_weight(samples)
            trust["last_updated"] = now

            # Calculate rolling expectancy (average R-multiple of last 10 trades)
            if r_mults:
                window = r_mults[-10:]
                trust["expectancy"] = round(sum(window) / len(window), 4)
            else:
                trust["expectancy"] = 0.0

            r.set(key, json.dumps(trust), ex=TRUST_TTL_SECONDS)

            logger.info("trust_updated",
                        bucket=key.split("trust:")[-1],
                        samples=samples, state=maturity,
                        trust=trust["trust_score"],
                        confidence=trust["confidence_weight"],
                        expectancy=trust["expectancy"],
                        outcome=ctx.outcome_score)
        except Exception as e:
            logger.warning("trust_update_failed", key=key, error=str(e))


# ═══════════════════════════════════════════
# TRUST QUERY — maturity-aware blending
# ═══════════════════════════════════════════

def _load_trust_bucket(r, key: str) -> dict:
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def get_pattern_trust(strategy: str, regime: str, asset_class: str) -> dict:
    r = _get_redis()
    default = {
        "blended_trust": TRUST_DEFAULT, "blended_confidence": 0.0,
        "maturity": "provisional", "total_trades": 0, "quick_stops": 0,
        "provisional": True, "buckets": {},
    }
    if not r:
        return default

    bucket_defs = [
        ("strategy", f"bahamut:training:trust:strategy:{strategy}", BLEND_STRATEGY),
        ("regime", f"bahamut:training:trust:strategy_regime:{strategy}:{regime}", BLEND_REGIME),
        ("class", f"bahamut:training:trust:strategy_class:{strategy}:{asset_class}", BLEND_CLASS),
        ("pattern", f"bahamut:training:trust:pattern:{strategy}:{regime}:{asset_class}", BLEND_PATTERN),
    ]

    buckets = {}
    total_trades = 0
    total_qs = 0

    for name, key, base_w in bucket_defs:
        data = _load_trust_bucket(r, key)
        samples = data.get("trades", 0)
        trust_val = data.get("trust_score", TRUST_DEFAULT)
        conf = get_confidence_weight(samples)
        decay = get_decay_factor(data.get("last_updated", ""))
        eff_conf = round(conf * decay, 3)

        buckets[name] = {
            "trust": trust_val, "samples": samples,
            "maturity": get_maturity_state(samples),
            "confidence": eff_conf, "base_weight": base_w,
            "quick_stops": data.get("quick_stops", 0), "decay": decay,
            "expectancy": data.get("expectancy", 0.0),
        }
        total_trades = max(total_trades, samples)
        total_qs += data.get("quick_stops", 0)

    # Sample-size-aware blending
    total_weight = 0.0
    weighted_trust = 0.0
    for info in buckets.values():
        eff_w = info["base_weight"] * info["confidence"]
        total_weight += eff_w
        weighted_trust += info["trust"] * eff_w

    blended_trust = round(weighted_trust / total_weight, 4) if total_weight > 0 else TRUST_DEFAULT

    total_base = sum(b["base_weight"] for b in buckets.values())
    blended_conf = round(sum(b["confidence"] * b["base_weight"] for b in buckets.values()) / total_base, 3) if total_base > 0 else 0.0

    maturities = [b["maturity"] for b in buckets.values() if b["samples"] > 0]
    if not maturities or all(m == "provisional" for m in maturities):
        overall = "provisional"
    elif sum(1 for m in maturities if m == "mature") >= 2:
        overall = "mature"
    else:
        overall = "developing"

    return {
        "blended_trust": blended_trust, "blended_confidence": blended_conf,
        "maturity": overall, "total_trades": total_trades,
        "quick_stops": total_qs, "provisional": overall == "provisional",
        "buckets": buckets,
        "expectancy": _calc_expectancy_from_buckets(buckets, r, strategy, regime, asset_class),
    }


def _calc_expectancy_from_buckets(buckets: dict, r, strategy: str, regime: str, asset_class: str) -> float:
    """Calculate rolling expectancy from the pattern-level trust bucket."""
    # Use pattern-level R-multiples (most specific)
    key = f"bahamut:training:trust:pattern:{strategy}:{regime}:{asset_class}"
    data = _load_trust_bucket(r, key)
    return calculate_expectancy(data.get("recent_r_multiples", []))


def calculate_expectancy(r_multiples: list) -> float:
    """Calculate rolling expectancy from a list of R-multiples.

    expectancy = average R-multiple of last N trades (max 10).
    > 0 = positive edge, < 0 = losing, ~0 = neutral.
    """
    if not r_multiples:
        return 0.0
    recent = r_multiples[-10:]  # Last 10 trades
    return round(sum(recent) / len(recent), 4)


# ═══════════════════════════════════════════
# SELECTOR HELPER
# ═══════════════════════════════════════════

def compute_trust_points(strategy: str, regime: str, asset_class: str, max_points: int = 20) -> dict:
    t = get_pattern_trust(strategy, regime, asset_class)

    raw_points = t["blended_trust"] * max_points
    neutral = max_points / 2
    # Scale by confidence: low confidence → stays near neutral
    points = neutral + (raw_points - neutral) * t["blended_confidence"]

    qs_penalty = 0
    if t["total_trades"] >= 5 and t["quick_stops"] >= 3:
        qs_penalty = 5
    elif t["total_trades"] >= 3 and t["quick_stops"] >= 2:
        qs_penalty = 3

    points = max(0, min(max_points, int(points) - qs_penalty))

    return {
        "points": points, "trust": t["blended_trust"],
        "confidence": t["blended_confidence"], "maturity": t["maturity"],
        "quick_stop_penalty": qs_penalty, "provisional": t["provisional"],
        "detail": f"trust={t['blended_trust']:.2f} conf={t['blended_confidence']:.2f} mat={t['maturity']} qs_pen={qs_penalty}",
    }


# ═══════════════════════════════════════════
# TRUST OVERVIEW — dashboard API
# ═══════════════════════════════════════════

def get_trust_overview() -> dict:
    r = _get_redis()
    if not r:
        return {"strategies": {}, "counts": {"provisional": 0, "developing": 0, "mature": 0}}

    counts = {"provisional": 0, "developing": 0, "mature": 0}
    strategies = {}

    for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
        data = _load_trust_bucket(r, f"bahamut:training:trust:strategy:{strat}")
        if not data:
            continue
        samples = data.get("trades", 0)
        maturity = get_maturity_state(samples)
        counts[maturity] = counts.get(maturity, 0) + 1
        strategies[strat] = {
            "trust": data.get("trust_score", TRUST_DEFAULT),
            "samples": samples, "maturity": maturity,
            "confidence": get_confidence_weight(samples),
            "wins": data.get("wins", 0), "losses": data.get("losses", 0),
            "quick_stops": data.get("quick_stops", 0),
        }

    return {"strategies": strategies, "counts": counts}


# ═══════════════════════════════════════════
# REJECTION TRACKING
# ═══════════════════════════════════════════

def record_rejection_reason(reason: str, asset: str = "", strategy: str = ""):
    r = _get_redis()
    if not r:
        return
    try:
        key = "bahamut:training:rejection_stats"
        raw = r.get(key)
        stats = json.loads(raw) if raw else {}
        stats[reason] = stats.get(reason, 0) + 1
        r.set(key, json.dumps(stats), ex=86400)
    except Exception:
        pass


def get_rejection_stats() -> dict:
    r = _get_redis()
    if not r:
        return {}
    try:
        raw = r.get("bahamut:training:rejection_stats")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}
