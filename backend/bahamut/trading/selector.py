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
        from bahamut.trading.adaptive_thresholds import get_current_profile
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
    # Phase 3 Item 7: sub-strategy tag (e.g. v10_range_long, v10_crash_short).
    # Non-v10 strategies leave empty — behavior unchanged.
    substrategy: str = ""
    # Phase 4 Item 12: data origin at signal generation. Inherited
    # from indicators._data_mode. Engine rejects synthetic_dev signals
    # in production.
    data_mode: str = "live"

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
        from bahamut.trading.learning_engine import compute_trust_points
        # crash_short signals use CRASH bucket for trust, not raw 4H regime
        _trust_regime = "CRASH" if signal.execution_type == "crash_short" else signal.regime
        tp = compute_trust_points(signal.strategy, _trust_regime, signal.asset_class, max_points=30)
        bd["trust"] = tp["points"]
        bd["_exp_bucket"] = f"{signal.strategy}:{_trust_regime}:{signal.asset_class}"
        bd["_exp_value"] = tp.get("expectancy", 0)
        bd["_exp_maturity"] = tp.get("maturity", "unknown")
        bd["_exp_samples"] = tp.get("samples", 0)

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

    # ── STRATEGY × CLASS STATIC PRIORS (override terms, not calibrated) ──
    # Phase 3 Item 8: these are hardcoded empirical priors from early
    # production data. They are OVERRIDE TERMS applied on top of the learned
    # trust/expectancy signal — not a substitute for it. Labeled explicitly
    # in the priority breakdown so operators can see them separately.
    #
    # ROADMAP: replace with calibrated priors derived from the actual
    # trust/expectancy buckets once per-substrategy data matures (Phase 3
    # Item 7 output). Target: remove these hardcoded numbers and compute
    # a prior from buckets[strategy_class].trust when samples >= 30.
    strat_class_key = f"{signal.strategy}:{signal.asset_class}"
    STRAT_CLASS_BOOSTS = {
        "v9_breakout:stock": 8,       # 74.4% WR, +$3476 — strongest edge
        "v10_mean_reversion:stock": 3, # 48.5% WR but +$2028 — decent
        "v5_base:stock": 3,            # 50% WR, +$1006 — ok
        "v10_mean_reversion:crypto": -10,  # 54.9% WR but -$816 PnL — negative expectancy
        "v5_base:crypto": -5,          # 44.7% WR, -$230 — weak
    }
    if strat_class_key in STRAT_CLASS_BOOSTS:
        # Key name signals this is a static override term, not a learned feature
        bd["class_boost_static_override"] = STRAT_CLASS_BOOSTS[strat_class_key]
        # Keep legacy key for existing diagnostics readers (UI expects "class_boost")
        bd["class_boost"] = STRAT_CLASS_BOOSTS[strat_class_key]

    total = sum(
        v for k, v in bd.items()
        if isinstance(v, (int, float))
        # Avoid double-counting — class_boost is a legacy alias for
        # class_boost_static_override; count only the canonical one.
        and k != "class_boost_static_override"
    )

    # 6. News risk — adaptive news is the SINGLE source of truth
    try:
        from bahamut.intelligence.adaptive_news_risk import (
            ADAPTIVE_NEWS_ENABLED, get_asset_news_state, get_news_gate_decision,
        )
        if ADAPTIVE_NEWS_ENABLED:
            state = get_asset_news_state(signal.asset)
            gate = get_news_gate_decision(state, signal.direction)
            bd["news_mode"] = gate["mode"]
            # Phase 4 Item 10: surface provenance in breakdown for diagnostics
            bd["news_origin"] = gate.get("dominant_origin", "none")
            bd["news_is_stale"] = gate.get("is_stale", False)
            bd["news_age_seconds"] = gate.get("age_seconds")
            bd["news_source_count"] = gate.get("source_count", 0)
            if not gate["allowed"]:
                bd["adaptive_news_block"] = True  # Canonical key — NOT "news_freeze"
                bd["adaptive_news_reason"] = gate["reason"]
            else:
                # Apply threshold penalty from news mode
                if gate["threshold_penalty"] > 0:
                    bd["news_threshold_penalty"] = -gate["threshold_penalty"]
                    total -= gate["threshold_penalty"]
                # Store size multiplier for engine
                bd["news_size_mult"] = gate["size_multiplier"]
                if gate["size_multiplier"] < 1.0:
                    bd["adaptive_news_sized"] = True
                # Track aligned trades that pass through RESTRICTED
                if gate["mode"] == "RESTRICTED":
                    bd["adaptive_news_aligned"] = True
        else:
            # Legacy fallback — only runs if ADAPTIVE_NEWS_ENABLED=False
            from bahamut.intelligence.news_impact import compute_news_impact_sync, compute_consensus_modifier
            assessment = compute_news_impact_sync(signal.asset, signal.asset_class)
            if assessment.impact_score > 0.1:
                mod = compute_consensus_modifier(assessment, signal.direction)
                bd["news_impact"] = mod["modifier"]
                total += mod["modifier"]
                if mod["action"] == "freeze":
                    bd["legacy_news_freeze"] = True
    except Exception:
        pass

    # 7. AI Decision Layer (global posture → derived per-candidate)
    # Layer A = Opus global posture (cached). Layer B = deterministic derivation.
    try:
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        ai_decision = get_ai_decision(
            asset=signal.asset, asset_class=signal.asset_class,
            strategy=signal.strategy, direction=signal.direction,
            priority_score=total,
        )
        ad = ai_decision.get("asset_decision", {})
        bd["ai_posture"] = ai_decision.get("posture", "UNKNOWN")
        bd["ai_class_mode"] = ai_decision.get("_class_mode", "NORMAL")
        bd["ai_global_size_mult"] = ai_decision.get("global_adjustments", {}).get("size_multiplier", 1.0)
        bd["ai_direction_allowed"] = ad.get("allowed", True)
        # Phase 4 Item 11: legacy _source string preserved for UI; canonical
        # ai_source field exposes one of fresh/stale/fallback_rules/disabled
        # along with cache age and the softening flag.
        bd["ai_source"] = ai_decision.get("_source", "unknown")
        bd["ai_source_category"] = ai_decision.get("ai_source", "fallback_rules")
        bd["ai_cache_age_seconds"] = ai_decision.get("ai_cache_age_seconds")
        bd["ai_posture_softened"] = ai_decision.get("ai_posture_softened", False)
        bd["ai_reason_compact"] = ad.get("reason", "")[:60]

        # Block if AI says not allowed
        if not ad.get("allowed", True):
            bd["ai_direction_block"] = True
            bd["ai_block_reason"] = (
                f"ai:{ai_decision.get('posture')}/{ai_decision.get('_class_mode')}"
                f" [{bd['ai_source_category']}]"
            )

        # Apply threshold penalty — max-severity rule: whichever penalty
        # (news or AI) is more severe wins, not both.
        ai_penalty = ad.get("threshold_penalty", 0)
        if ai_penalty < 0:
            existing_news = bd.get("news_threshold_penalty", 0)  # already negative
            if existing_news == 0:
                # No news penalty — apply AI directly
                bd["ai_threshold_penalty"] = ai_penalty
                total += ai_penalty
            elif ai_penalty < existing_news:
                # AI is more severe than news — swap them
                total -= existing_news  # reverse out news penalty
                del bd["news_threshold_penalty"]
                bd["ai_threshold_penalty"] = ai_penalty
                total += ai_penalty
            # else: news was more severe, keep it as-is

        # Store size multiplier for engine
        bd["ai_size_mult"] = ad.get("size_multiplier", 1.0)
    except Exception:
        bd["ai_fallback_used"] = True

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
    from bahamut.trading.engine import _load_positions
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
    from bahamut.trading.portfolio_optimizer import (
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
            from bahamut.trading.learning_engine import record_rejection_reason
            record_rejection_reason(reason)
        except Exception:
            pass

    for item in scored:
        sig = item["signal"]
        pri = item["priority"]
        reasons: list[str] = []
        # Phase 3 Item 8: per-candidate gate trace — records every gate
        # evaluation with its verdict for structured decision audit.
        gate_history: list[dict] = []

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
                from bahamut.trading.context_gate import pre_score_gate
                gate = pre_score_gate(sig.strategy, sig.regime, sig.asset_class,
                                      sig.direction, mode="TRAINING")
                if not gate["allowed"]:
                    reasons.append(gate["reason"])
                    gate_history.append({
                        "stage": "hard_safety", "gate": "context_gate",
                        "verdict": "block", "detail": gate["reason"],
                    })
                    rejected.append(_fmt_decision(sig, pri, "REJECT", reasons, gate_history))
                    _track_rejection(gate["gate"])
                    logger.info("selector_context_blocked",
                                asset=sig.asset, strategy=sig.strategy,
                                regime=sig.regime, gate=gate["gate"])
                    continue
                if gate["penalty"] > 0:
                    pri["components"]["context_penalty"] = -gate["penalty"]
                    pri["total"] -= gate["penalty"]
                    gate_history.append({
                        "stage": "hard_safety", "gate": "context_gate",
                        "verdict": "penalize", "detail": f"penalty={gate['penalty']}",
                    })
                else:
                    gate_history.append({
                        "stage": "hard_safety", "gate": "context_gate",
                        "verdict": "allow", "detail": "",
                    })
            except Exception:
                pass

        # 0.5. MATURE-NEGATIVE EXPECTANCY HARD BLOCK
        try:
            from bahamut.trading.learning_engine import compute_trust_points
            _exp_regime = "CRASH" if sig.execution_type == "crash_short" else sig.regime
            _tp = compute_trust_points(sig.strategy, _exp_regime, sig.asset_class, max_points=30)
            pri["components"]["_exp_bucket"] = f"{sig.strategy}:{_exp_regime}:{sig.asset_class}"
            pri["components"]["_exp_value"] = round(_tp.get("expectancy", 0), 4)
            pri["components"]["_exp_samples"] = _tp.get("samples", 0)
            pri["components"]["_exp_maturity"] = _tp.get("maturity", "unknown")
            _blocked_by_neg = False
            if _tp["maturity"] == "mature" and _tp.get("samples", 0) >= 15:
                _exp = _tp.get("expectancy", 0)
                if _exp < -0.07:
                    reasons.append(f"Mature negative expectancy {_exp:.3f} — hard blocked (bucket={sig.strategy}:{_exp_regime}:{sig.asset_class})")
                    gate_history.append({
                        "stage": "hard_safety", "gate": "mature_neg_expectancy",
                        "verdict": "block",
                        "detail": f"expectancy={_exp:.3f}, samples={_tp['samples']}",
                    })
                    rejected.append(_fmt_decision(sig, pri, "REJECT", reasons, gate_history))
                    _track_rejection("mature_negative_expectancy_block")
                    logger.info("selector_mature_neg_blocked",
                                asset=sig.asset, strategy=sig.strategy,
                                regime=sig.regime, exp_regime=_exp_regime,
                                asset_class=sig.asset_class,
                                expectancy=_exp, samples=_tp["samples"],
                                execution_type=sig.execution_type)
                    _blocked_by_neg = True
                elif _exp < -0.03:
                    pri["components"]["expectancy_penalty"] = max(-5, int(_exp * 40))
                    pri["components"]["_exp_penalty_mode"] = "reduced"
                    pri["total"] = sum(v for v in pri["components"].values() if isinstance(v, (int, float)))
                    gate_history.append({
                        "stage": "hard_safety", "gate": "mature_neg_expectancy",
                        "verdict": "penalize",
                        "detail": f"expectancy={_exp:.3f}, penalty={pri['components']['expectancy_penalty']}",
                    })
                    logger.info("selector_mature_neg_penalty",
                                asset=sig.asset, strategy=sig.strategy,
                                expectancy=_exp, penalty=pri["components"]["expectancy_penalty"],
                                execution_type=sig.execution_type)
                else:
                    gate_history.append({
                        "stage": "hard_safety", "gate": "mature_neg_expectancy",
                        "verdict": "allow",
                        "detail": f"expectancy={_exp:.3f}",
                    })
            else:
                gate_history.append({
                    "stage": "hard_safety", "gate": "mature_neg_expectancy",
                    "verdict": "allow",
                    "detail": f"maturity={_tp.get('maturity', 'unknown')}, samples={_tp.get('samples', 0)}",
                })
            if _blocked_by_neg:
                continue
        except Exception:
            pass

        # 0.6. QUALITY FLOORS
        if sig.execution_type != "debug_exploration":
            try:
                from bahamut.trading.quality_floors import check_quality_floors
                qf = check_quality_floors(
                    readiness_score=sig.readiness_score,
                    sl_pct=sig.sl_pct, tp_pct=sig.tp_pct,
                    strategy=sig.strategy, regime=sig.regime,
                    asset_class=sig.asset_class, asset=sig.asset,
                    mode="TRAINING",
                    execution_type=sig.execution_type,
                )
                if not qf["passed"]:
                    reasons.append(qf["summary"])
                    verdict = "block" if qf["action"] == "reject" else "watchlist"
                    gate_history.append({
                        "stage": "hard_safety", "gate": "quality_floors",
                        "verdict": verdict, "detail": qf["summary"],
                    })
                    if qf["action"] == "reject":
                        rejected.append(_fmt_decision(sig, pri, "REJECT", reasons, gate_history))
                        for f in qf["failures"]:
                            _track_rejection(f"quality_floor_{f['floor']}")
                    else:
                        watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
                        _track_rejection("quality_floor_watchlist")
                    continue
                else:
                    gate_history.append({
                        "stage": "hard_safety", "gate": "quality_floors",
                        "verdict": "allow", "detail": "",
                    })
            except Exception:
                pass

        # 0.8. RISK ENGINE GATE
        try:
            from bahamut.trading.risk_engine import can_open_new_trade
            re_check = can_open_new_trade(sig.asset, sig.strategy, sig.direction, sig.asset_class)
            if not re_check["allowed"]:
                reasons.append(f"Risk engine: {re_check['reason']}")
                gate_history.append({
                    "stage": "hard_safety", "gate": "risk_engine",
                    "verdict": "block", "detail": re_check["reason"],
                })
                rejected.append(_fmt_decision(sig, pri, "REJECT", reasons, gate_history))
                _track_rejection("risk_engine_block")
                logger.info("selector_risk_engine_blocked",
                            asset=sig.asset, strategy=sig.strategy,
                            direction=sig.direction, reason=re_check["reason"])
                continue
            else:
                gate_history.append({
                    "stage": "hard_safety", "gate": "risk_engine",
                    "verdict": "allow", "detail": "",
                })
        except Exception:
            pass

        # 1. Hard threshold (debug_exploration signals bypass this)
        effective_threshold = threshold
        if sig.direction == "SHORT":
            effective_threshold = 25
        elif sig.regime == "CRASH":
            effective_threshold = 35

        if sig.readiness_score < effective_threshold and sig.execution_type != "debug_exploration":
            reasons.append(f"Readiness {sig.readiness_score} < threshold {effective_threshold}")
            gate_history.append({
                "stage": "eligibility", "gate": "threshold",
                "verdict": "block",
                "detail": f"readiness={sig.readiness_score} < {effective_threshold}",
            })
            rejected.append(_fmt_decision(sig, pri, "REJECT", reasons, gate_history))
            _track_rejection("threshold")
            continue
        else:
            gate_history.append({
                "stage": "eligibility", "gate": "threshold",
                "verdict": "allow",
                "detail": f"readiness={sig.readiness_score}",
            })

        # 2. Portfolio optimizer check
        opt = evaluate_candidate(
            asset=sig.asset, asset_class=sig.asset_class,
            strategy=sig.strategy, direction=sig.direction,
            portfolio_snap=portfolio_snap,
        )
        if opt["decision"] == "BLOCK":
            reasons.extend(opt["reasons"])
            gate_history.append({
                "stage": "eligibility", "gate": "portfolio_optimizer",
                "verdict": "block", "detail": "; ".join(opt["reasons"]),
            })
            dec = _fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history)
            dec["optimizer"] = opt
            optimizer_blocked.append(dec)
            watchlist.append(dec)
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
            gate_history.append({
                "stage": "eligibility", "gate": "portfolio_optimizer",
                "verdict": "penalize",
                "detail": f"penalty={opt['penalty']}; {'; '.join(opt['reasons'])}",
            })
        else:
            gate_history.append({
                "stage": "eligibility", "gate": "portfolio_optimizer",
                "verdict": "allow", "detail": "",
            })

        # 3. News risk gate
        comp = pri.get("components", {})
        if comp.get("adaptive_news_block"):
            news_mode = comp.get("news_mode", "FROZEN")
            news_reason = comp.get("adaptive_news_reason", "blocked")
            reasons.append(f"Adaptive news: {news_mode} — {news_reason}")
            gate_history.append({
                "stage": "eligibility", "gate": "adaptive_news",
                "verdict": "watchlist", "detail": f"{news_mode} — {news_reason}",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("adaptive_news_block")
            continue
        elif comp.get("legacy_news_freeze"):
            reasons.append("Legacy news freeze — trading paused")
            gate_history.append({
                "stage": "eligibility", "gate": "adaptive_news",
                "verdict": "watchlist", "detail": "legacy news freeze",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("legacy_news_freeze")
            continue
        else:
            gate_history.append({
                "stage": "eligibility", "gate": "adaptive_news",
                "verdict": "allow", "detail": comp.get("news_mode", "OPEN"),
            })

        # 3b. AI direction gate
        if comp.get("ai_direction_block"):
            ai_reason = comp.get("ai_block_reason", "ai_blocked")
            reasons.append(f"AI decision: {ai_reason}")
            gate_history.append({
                "stage": "eligibility", "gate": "ai_direction",
                "verdict": "watchlist", "detail": ai_reason,
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("ai_direction_block")
            continue
        else:
            gate_history.append({
                "stage": "eligibility", "gate": "ai_direction",
                "verdict": "allow", "detail": "",
            })

        # 4. Position cap
        if current_count + len(execute) >= max_total:
            reasons.append(f"Portfolio full ({current_count + len(execute)}/{max_total})")
            gate_history.append({
                "stage": "eligibility", "gate": "position_cap",
                "verdict": "watchlist",
                "detail": f"full ({current_count + len(execute)}/{max_total})",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("position_cap")
            continue

        # 5. Per-cycle cap
        if len(execute) >= max_new:
            reasons.append(f"Cycle cap reached ({max_new} max per cycle)")
            gate_history.append({
                "stage": "eligibility", "gate": "cycle_cap",
                "verdict": "watchlist", "detail": f"cycle max {max_new}",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("cycle_cap")
            continue

        # 6. Per-class cap (per cycle)
        cls = sig.asset_class
        if class_counts.get(cls, 0) >= max_per_class:
            reasons.append(f"Class cap reached ({cls}: {max_per_class} max per cycle)")
            gate_history.append({
                "stage": "eligibility", "gate": "class_cap",
                "verdict": "watchlist",
                "detail": f"{cls}={class_counts.get(cls, 0)}/{max_per_class}",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("class_cap")
            continue

        # 7. Duplicate asset
        if sig.asset in selected_assets:
            reasons.append(f"Already selected {sig.asset} this cycle")
            gate_history.append({
                "stage": "eligibility", "gate": "duplicate_asset",
                "verdict": "watchlist", "detail": sig.asset,
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("duplicate_asset")
            continue

        # 8. Near-duplicate (same class + strategy)
        same_class_same_strat = any(
            e["asset_class"] == cls and e["strategy"] == sig.strategy
            for e in execute
        )
        if same_class_same_strat:
            reasons.append(f"Similar setup already selected ({cls}/{sig.strategy})")
            gate_history.append({
                "stage": "eligibility", "gate": "near_duplicate",
                "verdict": "watchlist", "detail": f"{cls}/{sig.strategy}",
            })
            watchlist.append(_fmt_decision(sig, pri, "WATCHLIST", reasons, gate_history))
            _track_rejection("duplicate_setup")
            continue

        # SELECTED — update portfolio snapshot for next candidates
        reason_text = _build_selection_reason(sig, pri, open_positions)
        if opt["decision"] == "PENALIZE":
            reason_text += f" (priority -{opt['penalty']}pts for overlap)"
        gate_history.append({
            "stage": "ranking", "gate": "execute",
            "verdict": "allow",
            "detail": f"priority={effective_priority}",
        })
        dec = _fmt_decision(sig, pri, "EXECUTE", [reason_text], gate_history)
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

        # Track adaptive news stats for approved trades (in-memory, persisted post-loop)
        comp2 = pri.get("components", {})
        if comp2.get("adaptive_news_aligned"):
            _track_rejection("_aligned_news_trades_allowed")  # positive counter, not a rejection
        if comp2.get("adaptive_news_sized"):
            _track_rejection("_adaptive_news_size_reductions")  # positive counter

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
        # NOTE: Do NOT overwrite bahamut:training:rejection_stats here.
        # record_rejection_reason() in learning_engine accumulates it cumulatively (TTL=24h).
        # A per-cycle setex here would destroy the cumulative totals.
        # Instead, persist per-cycle snapshot under a separate key for debugging.
        rc.setex("bahamut:training:rejection_stats_cycle", 900, json.dumps(rejection_reasons, default=str))
    except Exception:
        pass

    # ── Batch counter persistence (own try block — must not share fate with decisions) ──
    try:
        import os as _os2, redis as _redis2
        _rc2 = _redis2.from_url(_os2.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        _rc2.ping()
        COUNTER_MAP = {
            "mature_negative_expectancy_block": "bahamut:counters:mature_neg_expectancy_blocks",
            "risk_engine_block":                "bahamut:counters:risk_engine_blocks",
            "adaptive_news_block":              "bahamut:counters:adaptive_news_blocks",
            "ai_direction_block":               "bahamut:counters:ai_direction_blocks",
            "_aligned_news_trades_allowed":      "bahamut:counters:aligned_news_trades_allowed",
            "_adaptive_news_size_reductions":    "bahamut:counters:adaptive_news_size_reductions",
        }
        _written = 0
        _cycle_counts = {}
        for reason_key, redis_key in COUNTER_MAP.items():
            count = rejection_reasons.get(reason_key, 0)
            short = redis_key.split(":")[-1]
            _cycle_counts[short] = count
            if count > 0:
                _rc2.incrby(redis_key, count)
                _rc2.expire(redis_key, 604800)
                _written += 1
        # Write proof: store this cycle's counter writes for diagnostics verification
        _rc2.setex("bahamut:counters:_last_cycle_writes", 600,
                    json.dumps(_cycle_counts, default=str))
        logger.info("selector_counters_persisted", written=_written, counts=_cycle_counts)
    except Exception as _ce:
        logger.warning("selector_counter_persist_failed", error=str(_ce)[:200])

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


def _fmt_decision(sig: PendingSignal, priority: dict, decision: str,
                  reasons: list, gate_history: list | None = None) -> dict:
    """Build a structured decision record for an evaluated candidate.

    Phase 3 Item 8 additions:
      - gate_history: ordered list of dicts recording every gate the
        candidate was evaluated by. Each entry:
          {"stage": "hard_safety" | "eligibility" | "ranking",
           "gate": "context_gate" | "mature_neg_expectancy" | ...,
           "verdict": "allow" | "penalize" | "block" | "watchlist",
           "detail": str}
      - decision_stage: which stage the final verdict came from.
      - blocking_gate: name of the gate that produced a non-EXECUTE verdict
        (empty if EXECUTE).
    Callers can construct gate_history progressively; legacy callers that
    pass None still work — an empty list is returned.
    """
    gh = gate_history or []
    blocking = ""
    stage = "ranking"
    if decision != "EXECUTE":
        # Find the last block/watchlist verdict in history, if any
        for entry in reversed(gh):
            if entry.get("verdict") in ("block", "watchlist"):
                blocking = entry.get("gate", "")
                stage = entry.get("stage", "ranking")
                break
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
        # Phase 3 Item 8: structured decision provenance
        "gate_history": gh,
        "decision_stage": stage,
        "blocking_gate": blocking,
        "substrategy": getattr(sig, "substrategy", "") or "",
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
        for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
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
