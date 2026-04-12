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
    "max_new_per_cycle": 5,         # Max new positions opened per cycle
    "max_per_class": 3,             # Max new positions per asset class per cycle
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
    """Compute composite priority score with breakdown.

    Trust scoring (0-20pts) now uses pattern-level trust from the enhanced
    learning engine. A strategy with bad trust in a specific regime gets
    real penalties, not just 5pts provisional.
    """
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
        bd["regime_quality"] = 8  # Range is valid for v10
    else:
        bd["regime_quality"] = 0

    # 4. Portfolio fit — penalize overlap (0-15 pts, start at 15, deduct)
    same_class_count = sum(1 for p in open_positions if p.get("asset_class") == signal.asset_class)
    same_asset_count = sum(1 for p in open_positions if p.get("asset") == signal.asset)
    overlap_penalty = same_asset_count * 15 + same_class_count * 3
    bd["portfolio_fit"] = max(0, 15 - overlap_penalty)

    # 5. Pattern trust (0-30 pts) — maturity-aware from learning engine
    try:
        from bahamut.training.learning_engine import compute_trust_points
        tp = compute_trust_points(signal.strategy, signal.regime, signal.asset_class, max_points=30)
        bd["trust"] = tp["points"]

        # Extra penalty for mature bad patterns
        if tp["maturity"] == "mature" and tp["trust"] < 0.35:
            bd["mature_bad_penalty"] = -10
        elif tp["maturity"] == "developing" and tp["trust"] < 0.30:
            bd["mature_bad_penalty"] = -5

        # ── EXPECTANCY-AWARE PENALTY ──
        # If a pattern has mature negative expectancy, penalize heavily.
        # This prevents the selector from sending known-bad patterns.
        exp = tp.get("expectancy", 0)
        exp_samples = tp.get("samples", 0)
        if tp["maturity"] == "mature" and exp < -0.05 and exp_samples >= 15:
            penalty = int(exp * 40)  # -0.12 expectancy → -5pts, -0.3 → -12pts
            bd["expectancy_penalty"] = max(-15, penalty)
    except Exception:
        bd["trust"] = 15  # Default neutral if learning engine unavailable

    # ── STRATEGY × CLASS ADJUSTMENTS ──
    # Based on class_strategy_matrix data (proven over 100+ trades)
    strat_class_key = f"{signal.strategy}:{signal.asset_class}"
    STRAT_CLASS_BOOSTS = {
        "v9_breakout:stock": 8,       # 74.4% WR, +$3476 — strongest edge
        "v10_mean_reversion:stock": 3, # 48.5% WR but +$2028 — decent
        "v5_base:stock": 3,            # 50% WR, +$1006 — ok
        "v10_mean_reversion:crypto": -10,  # 54.9% WR but -$816 PnL — negative expectancy
        "v5_base:crypto": -5,          # 44.7% WR, -$230 — weak
    }
    if strat_class_key in STRAT_CLASS_BOOSTS:
        bd["class_boost"] = STRAT_CLASS_BOOSTS[strat_class_key]

    total = sum(bd.values())

    # 6. News impact modifier (0 to ±15 pts) — from deterministic news equations
    try:
        from bahamut.intelligence.news_impact import compute_news_impact_sync, compute_consensus_modifier
        assessment = compute_news_impact_sync(signal.asset, signal.asset_class)
        if assessment.impact_score > 0.1:
            mod = compute_consensus_modifier(assessment, signal.direction)
            bd["news_impact"] = mod["modifier"]
            total += mod["modifier"]
            if mod["action"] == "freeze":
                bd["news_freeze"] = True
    except Exception:
        pass  # News impact unavailable — no modifier applied

    return {"components": bd, "total": total}


# ═══════════════════════════════════════════
# SELECTION ENGINE
# ═══════════════════════════════════════════

def select_candidates(signals: list[PendingSignal]) -> dict:
    """
    Main selection function with portfolio optimization.
    """
    config = _get_config()
    threshold = config["execution_threshold"]
    max_new = config["max_new_per_cycle"]
    max_per_class = config["max_per_class"]
    max_total = config["max_total_positions"]

    # ── HARD LOG: every signal entering selector ──
    logger.info("selector_entry",
                total_signals=len(signals),
                threshold=threshold, max_new=max_new,
                max_per_class=max_per_class, max_total=max_total,
                debug_signals=sum(1 for s in signals if s.execution_type == "debug_exploration"),
                signal_assets=[s.asset for s in signals[:10]])

    # Load current portfolio state
    from bahamut.training.engine import _load_positions
    positions_raw = _load_positions()
    open_positions = [
        {"asset": p.asset, "asset_class": p.asset_class,
         "strategy": p.strategy, "direction": p.direction}
        for p in positions_raw
    ]
    current_count = len(open_positions)

    logger.info("selector_portfolio_state",
                open_positions=current_count, max_total=max_total)

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
    rejection_reasons: dict[str, int] = {}

    def _track_rejection(reason: str):
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        try:
            from bahamut.training.learning_engine import record_rejection_reason
            record_rejection_reason(reason)
        except Exception:
            pass

    for item in scored:
        sig = item["signal"]
        pri = item["priority"]
        reasons: list[str] = []

        # ── HARD LOG: every signal considered ──
        logger.info("selector_considering",
                    asset=sig.asset, strategy=sig.strategy,
                    score=sig.readiness_score, direction=sig.direction,
                    regime=sig.regime, exec_type=sig.execution_type,
                    priority=pri["total"],
                    trust_pts=pri["components"].get("trust", "?"))

        # 0. CONTEXT GATE — hard-block invalid strategy/regime combos + suppression
        if sig.execution_type != "debug_exploration":
            try:
                from bahamut.training.context_gate import pre_score_gate
                gate = pre_score_gate(sig.strategy, sig.regime, sig.asset_class,
                                      sig.direction, mode="TRAINING")
                if not gate["allowed"]:
                    reasons.append(gate["reason"])
                    rejected.append(_fmt_decision(sig, pri, "REJECT", reasons))
                    _track_rejection(gate["gate"])
                    logger.info("selector_context_blocked",
                                asset=sig.asset, strategy=sig.strategy,
                                regime=sig.regime, gate=gate["gate"])
                    continue
                if gate["penalty"] > 0:
                    pri["components"]["context_penalty"] = -gate["penalty"]
                    pri["total"] -= gate["penalty"]
            except Exception:
                pass

        # 0.5. MATURE-NEGATIVE EXPECTANCY HARD BLOCK
        # If a pattern has mature negative expectancy below -0.05 with 15+ samples,
        # this is a proven losing edge. Block it completely, not just penalize.
        # This is separate from selector penalties — it's a gate.
        try:
            from bahamut.training.learning_engine import compute_trust_points
            _tp = compute_trust_points(sig.strategy, sig.regime, sig.asset_class, max_points=30)
            if _tp["maturity"] == "mature" and _tp.get("expectancy", 0) < -0.05 and _tp.get("samples", 0) >= 15:
                reasons.append(f"Mature negative expectancy {_tp['expectancy']:.3f} — hard blocked")
                rejected.append(_fmt_decision(sig, pri, "REJECT", reasons))
                _track_rejection("mature_negative_expectancy_block")
                logger.info("selector_mature_neg_blocked",
                            asset=sig.asset, strategy=sig.strategy,
                            regime=sig.regime, asset_class=sig.asset_class,
                            expectancy=_tp["expectancy"], samples=_tp["samples"])
                try:
                    import redis as _rds, os
                    _rc = _rds.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    _rc.incr("bahamut:counters:mature_neg_expectancy_blocks")
                    _rc.expire("bahamut:counters:mature_neg_expectancy_blocks", 604800)
                except Exception: pass
                continue
        except Exception:
            pass

        # 0.6. QUALITY FLOORS — hard minimum requirements before ranking
        if sig.execution_type != "debug_exploration":
            try:
                from bahamut.training.quality_floors import check_quality_floors
                qf = check_quality_floors(
                    readiness_score=sig.readiness_score,
                    sl_pct=sig.sl_pct, tp_pct=sig.tp_pct,
                    strategy=sig.strategy, regime=sig.regime,
                    asset_class=sig.asset_class, asset=sig.asset,
                    mode="TRAINING",
                )
                if not qf["passed"]:
                    reasons.append(qf["summary"])
                    if qf["action"] == "reject":
                        rejected.append(_fmt_decision(sig, pri, "REJECT", reasons))
                        for f in qf["failures"]:
                            _track_rejection(f"quality_floor_{f['floor']}")
                    else:
                        watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
                        _track_rejection("quality_floor_watchlist")
                    continue
            except Exception:
                pass

        # 1. Hard threshold (debug_exploration signals bypass this)
        # SHORT signals get minimum threshold — they're new patterns in training.
        # The readiness scorer was designed for LONGs and gives low scores to SHORTs.
        # Quality floors (min_readiness=25) already filter garbage.
        effective_threshold = threshold
        if sig.direction == "SHORT":
            effective_threshold = 25  # Match quality floor minimum
        elif sig.regime == "CRASH":
            effective_threshold = 35  # Relaxed for CRASH regime

        if sig.readiness_score < effective_threshold and sig.execution_type != "debug_exploration":
            reasons.append(f"Readiness {sig.readiness_score} < threshold {effective_threshold}")
            rejected.append(_fmt_decision(sig, pri, "REJECT", reasons))
            _track_rejection("threshold")
            continue

        # 2. Portfolio optimizer check
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
            # Track specific block reasons
            for r in opt["reasons"]:
                if "cluster" in r.lower():
                    _track_rejection("cluster_overlap")
                elif "direction" in r.lower():
                    _track_rejection("direction_full")
                elif "already holding" in r.lower():
                    _track_rejection("already_holding_asset")
                else:
                    _track_rejection("portfolio_blocked")
            continue

        effective_priority = pri["total"]
        if opt["decision"] == "PENALIZE":
            effective_priority -= opt["penalty"]
            reasons.extend(opt["reasons"])

        # 3. News impact freeze check
        if pri.get("components", {}).get("news_freeze"):
            reasons.append("News/event freeze active — trading paused")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("news_freeze")
            continue

        # 4. Position cap
        if current_count + len(execute) >= max_total:
            reasons.append(f"Portfolio full ({current_count + len(execute)}/{max_total})")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("position_cap")
            continue

        # 5. Per-cycle cap
        if len(execute) >= max_new:
            reasons.append(f"Cycle cap reached ({max_new} max per cycle)")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("cycle_cap")
            continue

        # 6. Per-class cap (per cycle)
        cls = sig.asset_class
        if class_counts.get(cls, 0) >= max_per_class:
            reasons.append(f"Class cap reached ({cls}: {max_per_class} max per cycle)")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("class_cap")
            continue

        # 7. Duplicate asset
        if sig.asset in selected_assets:
            reasons.append(f"Already selected {sig.asset} this cycle")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("duplicate_asset")
            continue

        # 8. Near-duplicate (same class + strategy)
        same_class_same_strat = any(
            e["asset_class"] == cls and e["strategy"] == sig.strategy
            for e in execute
        )
        if same_class_same_strat:
            reasons.append(f"Similar setup already selected ({cls}/{sig.strategy})")
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons))
            _track_rejection("duplicate_setup")
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

        logger.info("selector_EXECUTE",
                    asset=sig.asset, strategy=sig.strategy,
                    score=sig.readiness_score, direction=sig.direction,
                    exec_type=sig.execution_type, priority=effective_priority,
                    total_selected=len(execute))

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

    # Store last cycle decisions in Redis for diagnostics
    try:
        import os, redis as _redis
        rc = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        all_decisions = []
        for d in execute[:5]:
            all_decisions.append({**d, "_action": "EXECUTE"})
        for d in rejected[:10]:
            all_decisions.append({**d, "_action": "REJECTED"})
        for d in watchlist[:5]:
            all_decisions.append({**d, "_action": "WATCHLIST"})
        rc.setex("bahamut:training:last_cycle_decisions", 300, json.dumps(all_decisions, default=str))
    except Exception:
        pass

    return {
        "execute": execute,
        "watchlist": watchlist,
        "rejected": rejected,
        "optimizer_blocked": optimizer_blocked,
        "portfolio_constraints": constraints,
        "rejection_reasons": rejection_reasons,
        "summary": {
            "total_signals": len(signals),
            "selected": len(execute),
            "watchlisted": len(watchlist),
            "rejected": len(rejected),
            "optimizer_blocked": len(optimizer_blocked),
            "rejection_breakdown": rejection_reasons,
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
        for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
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
