"""
Bahamut.AI — Training Candidate Selection Engine

Decides WHICH candidates to execute when multiple assets signal simultaneously.
Applies portfolio-aware filtering, diversification, and risk caps.

Pipeline:
  1. Collect all signals from the training cycle
  2. Score each with composite priority (readiness + risk/reward + portfolio fit)
  3. Apply hard threshold (configurable, default 80)
  4. Apply per-cycle cap (max new trades per cycle)
  5. Apply diversification rules (no class domination)
  6. Classify: EXECUTE / WATCHLIST / REJECT

TRAINING ONLY — does not touch production execution.
"""
import json
import os
import structlog
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════

DEFAULT_CONFIG = {
    "execution_threshold": 80,      # Minimum readiness score to be eligible
    "max_new_per_cycle": 3,         # Max new positions opened per cycle
    "max_per_class": 2,             # Max new positions per asset class per cycle
    "max_total_positions": 20,      # Hard cap on total open positions
    "class_diversity_min": 2,       # Try to spread across at least N classes
    "require_regime_alignment": True,  # Require TREND or BREAKOUT regime
}


def _get_config() -> dict:
    """Load selector config — adaptive thresholds override defaults."""
    config = dict(DEFAULT_CONFIG)

    # Apply adaptive thresholds if available
    try:
        from bahamut.training.adaptive_thresholds import get_current_profile
        profile = get_current_profile()
        if profile.mode != "WARMING_UP":
            config["execution_threshold"] = profile.standard_threshold
            config["max_new_per_cycle"] = max(config["max_new_per_cycle"],
                                               profile.max_early_per_cycle)
    except Exception:
        pass

    # Manual Redis override takes highest priority
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get("bahamut:training:selector_config")
        if raw:
            override = json.loads(raw)
            config.update(override)
    except Exception:
        pass

    return config


# ═══════════════════════════════════════════
# SIGNAL CONTAINER
# ═══════════════════════════════════════════

@dataclass
class PendingSignal:
    """A signal awaiting selection decision."""
    asset: str
    asset_class: str
    strategy: str
    direction: str
    readiness_score: int
    regime: str
    entry_price: float
    sl_pct: float
    tp_pct: float
    max_hold_bars: int
    reasons: list
    execution_type: str = "standard"       # "standard" | "early"
    confidence_score: float = 0.0
    trigger_reason: str = "4h_close"       # "4h_close" | "early_signal"
    risk_multiplier: float = 1.0           # 0.5 for early trades
    indicators: dict = None

    def __post_init__(self):
        if self.indicators is None:
            self.indicators = {}


# ═══════════════════════════════════════════
# COMPOSITE PRIORITY SCORING
# ═══════════════════════════════════════════

def _compute_priority(signal: PendingSignal, open_positions: list, strategy_stats: dict) -> dict:
    """Compute composite priority score with breakdown."""
    bd = {}

    # 1. Readiness (0-40 pts) — direct from candidate score
    bd["readiness"] = min(40, int(signal.readiness_score * 0.4))

    # 2. Reward/Risk ratio (0-20 pts)
    rr = signal.tp_pct / max(signal.sl_pct, 0.01)
    bd["reward_risk"] = min(20, int(rr * 5))

    # 3. Regime quality (0-15 pts)
    if signal.regime in ("TREND", "BREAKOUT"):
        bd["regime_quality"] = 15
    elif signal.regime == "RANGE":
        bd["regime_quality"] = 5
    else:
        bd["regime_quality"] = 0

    # 4. Portfolio fit — penalize overlap (0-15 pts, start at 15, deduct)
    same_class_count = sum(1 for p in open_positions if p.get("asset_class") == signal.asset_class)
    same_asset_count = sum(1 for p in open_positions if p.get("asset") == signal.asset)
    overlap_penalty = same_asset_count * 15 + same_class_count * 3
    bd["portfolio_fit"] = max(0, 15 - overlap_penalty)

    # 5. Strategy track record (0-10 pts)
    strat_record = strategy_stats.get(signal.strategy, {})
    strat_trades = strat_record.get("trades", 0)
    strat_wr = strat_record.get("win_rate", 0.5)
    if strat_trades >= 10:
        bd["strategy_track"] = min(10, int(strat_wr * 15))
    else:
        bd["strategy_track"] = 5  # Provisional — not penalized, not boosted

    total = sum(bd.values())
    return {"components": bd, "total": total}


# ═══════════════════════════════════════════
# SELECTION ENGINE
# ═══════════════════════════════════════════

def select_candidates(signals: list[PendingSignal]) -> dict:
    """
    Main selection function with portfolio optimization.

    Pipeline:
      1. Score with composite priority
      2. Hard threshold → REJECT
      3. Regime check → WATCHLIST
      4. Portfolio optimizer (correlation/direction/cluster) → BLOCK/PENALIZE
      5. Caps (cycle/class/duplicate) → WATCHLIST
      6. Remaining → EXECUTE (updates portfolio snapshot for next candidate)
    """
    config = _get_config()
    threshold = config["execution_threshold"]
    max_new = config["max_new_per_cycle"]
    max_per_class = config["max_per_class"]
    max_total = config["max_total_positions"]

    # Load current portfolio state
    from bahamut.training.engine import _load_positions
    positions_raw = _load_positions()
    open_positions = [
        {"asset": p.asset, "asset_class": p.asset_class,
         "strategy": p.strategy, "direction": p.direction}
        for p in positions_raw
    ]
    current_count = len(open_positions)

    # Load strategy stats
    strategy_stats = _load_strategy_stats()

    # Build mutable portfolio snapshot for optimizer
    from bahamut.training.portfolio_optimizer import (
        evaluate_candidate, _build_portfolio_snapshot,
        get_portfolio_constraints_summary, _ASSET_CLUSTERS,
    )
    portfolio_snap = _build_portfolio_snapshot(open_positions)

    # Score all signals
    scored = []
    for sig in signals:
        priority = _compute_priority(sig, open_positions, strategy_stats)
        scored.append({
            "signal": sig,
            "priority": priority,
            "readiness": sig.readiness_score,
        })

    scored.sort(key=lambda x: x["priority"]["total"], reverse=True)

    execute = []
    watchlist = []
    rejected = []
    optimizer_blocked = []
    class_counts: dict[str, int] = {}
    selected_assets: set[str] = set()

    for item in scored:
        sig = item["signal"]
        pri = item["priority"]
        reasons: list[str] = []

        # 1. Hard threshold
        if sig.readiness_score < threshold:
            reasons.append(f"Readiness {sig.readiness_score} < threshold {threshold}")
            rejected.append(_fmt_decision(sig, pri, "REJECT", reasons))
            continue

        # 2. Regime check
        if config["require_regime_alignment"] and sig.regime not in ("TREND", "BREAKOUT"):
            reasons.append(f"Regime {sig.regime} not aligned (need TREND or BREAKOUT)")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # 3. Portfolio optimizer check
        opt = evaluate_candidate(
            asset=sig.asset, asset_class=sig.asset_class,
            strategy=sig.strategy, direction=sig.direction,
            portfolio_snap=portfolio_snap,
        )
        if opt["decision"] == "BLOCK":
            reasons.extend(opt["reasons"])
            dec = _fmt_decision(sig, pri, "WATCHLIST", reasons)
            dec["optimizer"] = opt
            optimizer_blocked.append(dec)
            watchlist.append(dec)
            continue

        effective_priority = pri["total"]
        if opt["decision"] == "PENALIZE":
            effective_priority -= opt["penalty"]
            reasons.extend(opt["reasons"])

        # 4. Position cap
        if current_count + len(execute) >= max_total:
            reasons.append(f"Portfolio full ({current_count + len(execute)}/{max_total})")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # 5. Per-cycle cap
        if len(execute) >= max_new:
            reasons.append(f"Cycle cap reached ({max_new} max per cycle)")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # 6. Per-class cap (per cycle)
        cls = sig.asset_class
        if class_counts.get(cls, 0) >= max_per_class:
            reasons.append(f"Class cap reached ({cls}: {max_per_class} max per cycle)")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # 7. Duplicate asset
        if sig.asset in selected_assets:
            reasons.append(f"Already selected {sig.asset} this cycle")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # 8. Near-duplicate
        same_class_same_strat = any(
            e["asset_class"] == cls and e["strategy"] == sig.strategy
            for e in execute
        )
        if same_class_same_strat:
            reasons.append(f"Similar setup already selected ({cls}/{sig.strategy})")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            continue

        # SELECTED — update portfolio snapshot for next candidates
        reason_text = _build_selection_reason(sig, pri, open_positions)
        if opt["decision"] == "PENALIZE":
            reason_text += f" (priority -{opt['penalty']}pts for overlap)"
        dec = _fmt_decision(sig, pri, "EXECUTE", [reason_text])
        dec["optimizer"] = opt
        dec["effective_priority"] = effective_priority
        execute.append(dec)
        class_counts[cls] = class_counts.get(cls, 0) + 1
        selected_assets.add(sig.asset)

        # Update snapshot so next candidates see this selection
        portfolio_snap["total"] += 1
        if sig.direction == "LONG":
            portfolio_snap["longs"] += 1
        else:
            portfolio_snap["shorts"] += 1
        portfolio_snap["by_class"][cls] = portfolio_snap["by_class"].get(cls, 0) + 1
        portfolio_snap["by_strategy"][sig.strategy] = portfolio_snap["by_strategy"].get(sig.strategy, 0) + 1
        portfolio_snap["assets"].add(sig.asset)
        dir_cls = f"{sig.direction}:{cls}"
        portfolio_snap["by_direction_class"][dir_cls] = portfolio_snap["by_direction_class"].get(dir_cls, 0) + 1
        for cid in _ASSET_CLUSTERS.get(sig.asset, []):
            portfolio_snap["by_cluster"][cid] = portfolio_snap["by_cluster"].get(cid, 0) + 1

    constraints = get_portfolio_constraints_summary(open_positions)

    return {
        "execute": execute,
        "watchlist": watchlist,
        "rejected": rejected,
        "optimizer_blocked": optimizer_blocked,
        "portfolio_constraints": constraints,
        "summary": {
            "total_signals": len(signals),
            "selected": len(execute),
            "watchlisted": len(watchlist),
            "rejected": len(rejected),
            "optimizer_blocked": len(optimizer_blocked),
            "config": config,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _fmt_decision(sig: PendingSignal, priority: dict, decision: str, reasons: list) -> dict:
    return {
        "asset": sig.asset,
        "asset_class": sig.asset_class,
        "strategy": sig.strategy,
        "direction": sig.direction,
        "readiness_score": sig.readiness_score,
        "priority_score": priority["total"],
        "priority_breakdown": priority["components"],
        "regime": sig.regime,
        "decision": decision,
        "reasons": reasons,
        "execution_type": sig.execution_type,
        "confidence_score": sig.confidence_score,
        "trigger_reason": sig.trigger_reason,
    }


def _build_selection_reason(sig: PendingSignal, pri: dict, positions: list) -> str:
    """Natural-language reason for selection."""
    parts = []
    parts.append(f"Highest priority ({pri['total']})")
    if sig.readiness_score >= 90:
        parts.append("very high readiness")
    if pri["components"].get("portfolio_fit", 0) >= 12:
        parts.append("good portfolio diversification")
    if pri["components"].get("reward_risk", 0) >= 15:
        parts.append(f"strong reward/risk ({sig.tp_pct/max(sig.sl_pct,0.01):.1f}:1)")
    if sig.regime in ("TREND", "BREAKOUT"):
        parts.append(f"{sig.regime.lower()} regime confirmed")
    return ". ".join(parts) + "."


def _load_strategy_stats() -> dict:
    """Load strategy performance from Redis."""
    stats = {}
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        for strat in ["v5_base", "v5_tuned", "v9_breakout"]:
            raw = r.get(f"bahamut:training:strategy_stats:{strat}")
            if raw:
                stats[strat] = json.loads(raw)
    except Exception:
        pass
    return stats


# ═══════════════════════════════════════════
# LAST DECISIONS CACHE (for API)
# ═══════════════════════════════════════════

def save_last_decisions(decisions: dict):
    """Save last selection result to Redis for dashboard API."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.set("bahamut:training:last_decisions", json.dumps(decisions), ex=900)  # 15 min TTL
    except Exception:
        pass


def get_last_decisions() -> dict:
    """Get last selection result from Redis."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get("bahamut:training:last_decisions")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"execute": [], "watchlist": [], "rejected": [], "summary": {"total_signals": 0, "selected": 0}}
