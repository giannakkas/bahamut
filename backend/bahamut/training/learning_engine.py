"""
Bahamut Training — Enhanced Learning Engine

Learns from closed trades at multiple granularities:
  1. Strategy-level trust      (v9_breakout → 0.62)
  2. Strategy+regime trust     (v9_breakout+RANGE → 0.38)
  3. Strategy+asset_class trust (v9_breakout+crypto → 0.55)
  4. Pattern trust             (v9_breakout+RANGE+crypto → 0.31)

Uses weighted scoring that differentiates:
  - Quick SL hit = strong negative (bad signal quality)
  - Full SL hit = moderate negative
  - Timeout scratch = mild negative or neutral
  - Timeout profit = mild positive
  - TP hit = strong positive

Trust scores are EMA-smoothed (not simple averages) to:
  - React gradually to new data
  - Not overfit to single outcomes
  - Weight recent trades more than old ones
"""
import json
import os
import structlog
from dataclasses import dataclass, asdict

logger = structlog.get_logger()

# ── Constants ──
MIN_TRADES_FOR_TRUST = 5        # Minimum trades before trust is non-provisional
TRUST_EMA_ALPHA = 0.15          # EMA smoothing factor (higher = more reactive)
TRUST_DEFAULT = 0.50            # Starting trust for new patterns
QUICK_SL_BARS = 3               # SL hit within 3 bars = "quick stop"


def _get_redis():
    import redis
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
# LEARNING CONTEXT — structured data from each closed trade
# ═══════════════════════════════════════════════════════

@dataclass
class LearningContext:
    """Structured learning data extracted from a closed trade."""
    strategy: str
    asset: str
    asset_class: str
    direction: str
    regime: str
    exit_reason: str          # SL / TP / TIMEOUT
    pnl: float
    r_multiple: float         # pnl / risk_amount
    bars_held: int
    quick_stop: bool          # SL hit within QUICK_SL_BARS
    outcome_score: float      # Weighted score (-1 to +1)


def compute_learning_context(trade_dict: dict) -> LearningContext:
    """Extract structured learning context from a closed trade.

    trade_dict should have: strategy, asset, asset_class, direction,
    regime, exit_reason, pnl, risk_amount, bars_held
    """
    pnl = float(trade_dict.get("pnl", 0))
    risk = float(trade_dict.get("risk_amount", 0))
    bars = int(trade_dict.get("bars_held", 0))
    exit_reason = str(trade_dict.get("exit_reason", "")).upper()

    r_multiple = pnl / risk if risk > 0 else 0.0
    quick_stop = exit_reason == "SL" and bars <= QUICK_SL_BARS

    # ── Compute outcome score (-1 to +1) ──
    if exit_reason == "TP":
        # Take profit hit → strong positive signal
        score = min(1.0, 0.6 + r_multiple * 0.1)
    elif exit_reason == "SL":
        if quick_stop:
            # Quick stop → very bad signal (entered at wrong time)
            score = max(-1.0, -0.8 - abs(r_multiple) * 0.1)
        else:
            # Normal SL → moderate negative
            score = max(-1.0, -0.4 - abs(r_multiple) * 0.1)
    elif exit_reason == "TIMEOUT":
        if pnl > 0:
            # Profitable timeout → mild positive
            score = min(0.5, 0.1 + r_multiple * 0.2)
        elif abs(r_multiple) < 0.2:
            # Scratch (near zero) → neutral
            score = -0.05
        else:
            # Losing timeout → mild negative
            score = max(-0.5, -0.15 - abs(r_multiple) * 0.1)
    else:
        # Manual or unknown → neutral
        score = 0.0

    return LearningContext(
        strategy=str(trade_dict.get("strategy", "")),
        asset=str(trade_dict.get("asset", "")),
        asset_class=str(trade_dict.get("asset_class", "")),
        direction=str(trade_dict.get("direction", "")),
        regime=str(trade_dict.get("regime", "")),
        exit_reason=exit_reason,
        pnl=round(pnl, 2),
        r_multiple=round(r_multiple, 4),
        bars_held=bars,
        quick_stop=quick_stop,
        outcome_score=round(score, 4),
    )


# ═══════════════════════════════════════════════════════
# TRUST UPDATE — EMA-smoothed at multiple granularities
# ═══════════════════════════════════════════════════════

def update_trust_from_trade(ctx: LearningContext):
    """Update trust scores at all granularity levels from a closed trade.

    Updates four keys in Redis:
      trust:strategy:{strategy}
      trust:strategy_regime:{strategy}:{regime}
      trust:strategy_class:{strategy}:{asset_class}
      trust:pattern:{strategy}:{regime}:{asset_class}

    Each trust object:
      trades: int
      trust_score: float (0-1, EMA-smoothed)
      recent_outcomes: list[float] (last 20 outcome scores)
      wins: int
      losses: int
      quick_stops: int
      last_updated: str
      provisional: bool
    """
    r = _get_redis()
    if not r:
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    keys = [
        f"bahamut:training:trust:strategy:{ctx.strategy}",
        f"bahamut:training:trust:strategy_regime:{ctx.strategy}:{ctx.regime}",
        f"bahamut:training:trust:strategy_class:{ctx.strategy}:{ctx.asset_class}",
        f"bahamut:training:trust:pattern:{ctx.strategy}:{ctx.regime}:{ctx.asset_class}",
    ]

    for key in keys:
        try:
            raw = r.get(key)
            trust = json.loads(raw) if raw else {
                "trades": 0, "wins": 0, "losses": 0, "quick_stops": 0,
                "trust_score": TRUST_DEFAULT, "recent_outcomes": [],
                "provisional": True, "last_updated": "",
            }

            # Update counts
            trust["trades"] += 1
            if ctx.pnl > 0:
                trust["wins"] += 1
            else:
                trust["losses"] += 1
            if ctx.quick_stop:
                trust["quick_stops"] += 1

            # Append outcome to rolling window
            recent = trust.get("recent_outcomes", [])
            recent.append(ctx.outcome_score)
            if len(recent) > 20:
                recent = recent[-20:]
            trust["recent_outcomes"] = recent

            # EMA-smooth the trust score
            if trust["trades"] >= MIN_TRADES_FOR_TRUST:
                # Map outcome_score (-1 to +1) → trust space (0 to 1)
                mapped = (ctx.outcome_score + 1) / 2  # -1→0, 0→0.5, +1→1
                old = trust["trust_score"]
                trust["trust_score"] = round(
                    old * (1 - TRUST_EMA_ALPHA) + mapped * TRUST_EMA_ALPHA, 4
                )
                trust["provisional"] = False
            else:
                # Provisional: use simple average of recent outcomes
                if recent:
                    avg = sum(recent) / len(recent)
                    trust["trust_score"] = round((avg + 1) / 2, 4)  # Map to 0-1
                trust["provisional"] = True

            trust["last_updated"] = now
            r.set(key, json.dumps(trust), ex=86400 * 30)  # 30-day TTL

        except Exception as e:
            logger.warning("trust_update_failed", key=key, error=str(e))

    logger.info("trust_updated",
                strategy=ctx.strategy, regime=ctx.regime,
                asset_class=ctx.asset_class,
                outcome=ctx.outcome_score, exit=ctx.exit_reason,
                quick_stop=ctx.quick_stop, r_mult=ctx.r_multiple)


# ═══════════════════════════════════════════════════════
# TRUST QUERY — get trust for a candidate before selection
# ═══════════════════════════════════════════════════════

def get_pattern_trust(strategy: str, regime: str, asset_class: str) -> dict:
    """Get trust scores for a strategy+regime+asset_class pattern.

    Returns dict with trust at all granularities + a blended score.
    Used by the selector to weight candidates.
    """
    r = _get_redis()
    result = {
        "strategy_trust": TRUST_DEFAULT,
        "regime_trust": TRUST_DEFAULT,
        "class_trust": TRUST_DEFAULT,
        "pattern_trust": TRUST_DEFAULT,
        "blended_trust": TRUST_DEFAULT,
        "provisional": True,
        "total_trades": 0,
        "quick_stops": 0,
    }

    if not r:
        return result

    keys_and_fields = [
        (f"bahamut:training:trust:strategy:{strategy}", "strategy_trust"),
        (f"bahamut:training:trust:strategy_regime:{strategy}:{regime}", "regime_trust"),
        (f"bahamut:training:trust:strategy_class:{strategy}:{asset_class}", "class_trust"),
        (f"bahamut:training:trust:pattern:{strategy}:{regime}:{asset_class}", "pattern_trust"),
    ]

    any_non_provisional = False
    for key, field in keys_and_fields:
        try:
            raw = r.get(key)
            if raw:
                trust = json.loads(raw)
                result[field] = trust.get("trust_score", TRUST_DEFAULT)
                if not trust.get("provisional", True):
                    any_non_provisional = True
                result["total_trades"] = max(result["total_trades"], trust.get("trades", 0))
                result["quick_stops"] += trust.get("quick_stops", 0)
        except Exception:
            pass

    # Blended trust: weighted average (pattern-level most specific = highest weight)
    result["blended_trust"] = round(
        result["strategy_trust"] * 0.2 +
        result["regime_trust"] * 0.3 +
        result["class_trust"] * 0.2 +
        result["pattern_trust"] * 0.3, 4
    )
    result["provisional"] = not any_non_provisional

    return result


# ═══════════════════════════════════════════════════════
# REJECTION REASON STATS — track why candidates are blocked
# ═══════════════════════════════════════════════════════

def record_rejection_reason(reason: str, asset: str = "", strategy: str = ""):
    """Track rejection reason counts for dashboard analytics."""
    r = _get_redis()
    if not r:
        return
    try:
        key = "bahamut:training:rejection_stats"
        raw = r.get(key)
        stats = json.loads(raw) if raw else {}
        stats[reason] = stats.get(reason, 0) + 1
        r.set(key, json.dumps(stats), ex=86400)  # Reset daily
    except Exception:
        pass


def get_rejection_stats() -> dict:
    """Get rejection reason counts for dashboard."""
    r = _get_redis()
    if not r:
        return {}
    try:
        raw = r.get("bahamut:training:rejection_stats")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}
