"""
Sync Paper Trading Executor — for Celery workers.
Uses execution policy as authoritative gate, then sync SQL for trade insertion.
"""
import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from bahamut.database import sync_engine

logger = structlog.get_logger(__name__)


def process_signal_sync(
    asset: str, direction: str, consensus_score: float,
    signal_label: str, entry_price: float, atr: float,
    agent_votes: dict, cycle_id: str = None,
    execution_gate: str = "CLEAR", disagreement_index: float = 0.0,
    risk_flags: list = None, risk_can_trade: bool = True,
    regime: str = "RISK_ON", trading_profile: str = "BALANCED",
) -> dict:
    """Sync version of process_signal for Celery workers."""
    import json
    risk_flags = risk_flags or []

    log = logger.bind(asset=asset, direction=direction, score=consensus_score)

    # ══════════════════════════════════════════════
    # TRACE: Signal received
    # ══════════════════════════════════════════════
    log.info("signal_received", asset=asset, direction=direction,
             score=consensus_score, label=signal_label, regime=regime,
             gate=execution_gate, disagree=disagreement_index,
             risk_can_trade=risk_can_trade, profile=trading_profile)

    if entry_price <= 0:
        log.info("exploration_condition", reason="invalid_price", price=entry_price)
        return {"action": "SKIP", "reason": "Invalid price"}

    # ── PRIMARY GATE: Disagreement (checked first, unconditionally) ──
    if execution_gate == "BLOCKED":
        log.info("exploration_condition", reason="disagreement_blocked",
                 index=disagreement_index, mode="STRICT")
        return {"action": "SKIP", "reason": f"Disagreement BLOCKED (index={disagreement_index:.3f})",
                "gate": "DISAGREEMENT", "disagreement_index": disagreement_index}

    # ── SIGNAL LABEL GATE with exploration fallback ──
    is_exploration = False
    if signal_label not in ("STRONG_SIGNAL", "SIGNAL"):
        log.info("exploration_condition",
                 asset=asset, score=consensus_score, label=signal_label,
                 reason="score_below_signal_threshold",
                 threshold_needed="SIGNAL (≥0.58 for BALANCED)")

        # Check exploration fallback
        log.info("exploration_condition",
                 asset=asset, score=consensus_score, label=signal_label)

        exploration_eligible, explore_reason = _check_exploration_eligible(
            asset, consensus_score, regime, signal_label)

        if not exploration_eligible:
            log.info("exploration_condition",
                     asset=asset, score=consensus_score, reason=explore_reason)
            log.info("exploration_condition",
                     asset=asset, mode="NONE",
                     strict_reason="weak_signal", exploration_reason=explore_reason)
            return {"action": "SKIP", "reason": f"Only SIGNAL+, got {signal_label}. {explore_reason}"}

        is_exploration = True
        log.info("exploration_condition",
                 asset=asset, score=consensus_score, label=signal_label,
                 reason=explore_reason)
    else:
        log.info("exploration_condition",
                 asset=asset, score=consensus_score, label=signal_label,
                 mode="STRICT")

    try:
        with sync_engine.connect() as conn:
            # Get or create portfolio via canonical store
            from bahamut.paper_trading.store import get_or_create_portfolio, get_open_position_count, has_open_position
            portfolio = get_or_create_portfolio("SYSTEM_DEMO")

            if not portfolio or not portfolio.get("is_active", True):
                return {"action": "SKIP", "reason": "Portfolio inactive"}

            pid = portfolio["id"]
            balance = portfolio["current_balance"]
            risk_pct = portfolio["risk_per_trade_pct"] or 2.0

            # Count open positions
            open_count = get_open_position_count(pid)

            # Check duplicate
            has_dup = has_open_position(pid, asset)

            # ── PORTFOLIO INTELLIGENCE — evaluates trade in portfolio context ──
            portfolio_verdict = None
            portfolio_size_mult = 1.0
            try:
                from bahamut.portfolio.registry import load_portfolio_snapshot
                from bahamut.portfolio.engine import evaluate_trade_for_portfolio

                snap = load_portfolio_snapshot()
                # Estimate proposed position value
                sl_est = (atr * 2.0) if atr > 0 else (entry_price * 0.01)
                risk_est = balance * (risk_pct / 100.0)
                qty_est = risk_est / sl_est if sl_est > 0 else 1
                val_est = qty_est * entry_price

                portfolio_verdict = evaluate_trade_for_portfolio(
                    snapshot=snap,
                    proposed_asset=asset,
                    proposed_direction=direction,
                    proposed_value=val_est,
                    proposed_risk=risk_est,
                    consensus_score=consensus_score,
                    signal_label=signal_label,
                    atr=atr,
                    entry_price=entry_price,
                )

                if not portfolio_verdict.allowed:
                    log.info("blocked_by_portfolio", blockers=portfolio_verdict.blockers)
                    return {"action": "SKIP", "reason": portfolio_verdict.blockers[0],
                            "blockers": portfolio_verdict.blockers, "gate": "PORTFOLIO"}

                portfolio_size_mult = portfolio_verdict.size_multiplier
            except Exception as e:
                log.debug("portfolio_intel_skipped", error=str(e))

            # ── EXECUTION POLICY — authoritative gate ──
            # Compute system confidence (composite of trust stability,
            # disagreement trend, recent performance, calibration health)
            sys_conf = 0.5
            mean_trust = 1.0
            try:
                from bahamut.consensus.system_confidence import get_system_confidence
                bd = get_system_confidence()
                sys_conf = bd.system_confidence
                mean_trust = bd.mean_agent_trust
            except Exception as e:
                logger.warning("system_confidence_unavailable_in_executor", error=str(e))

            # Feed portfolio intelligence into execution policy
            augmented_flags = list(risk_flags)
            if portfolio_verdict:
                for w in portfolio_verdict.warnings:
                    if "CORRELATED" in w or "CLASS_CONCENTRATION" in w:
                        augmented_flags.append("HIGH_CORRELATION")
                    if "THEME_CONCENTRATION" in w or "THEME_OVERLAP" in w:
                        augmented_flags.append("HIGH_EXPOSURE")
                if portfolio_verdict.requires_approval:
                    augmented_flags.append("PORTFOLIO_FRAGILE")
                ks = portfolio_verdict.kill_switch_state
                if ks.get("safe_mode_active"):
                    augmented_flags.append("SAFE_MODE")

            from bahamut.execution.policy import execution_policy, ExecutionRequest

            # Exploration: override risk to 0.5% (vs normal 2%)
            effective_risk_pct = risk_pct
            if is_exploration:
                effective_risk_pct = 0.5

            exec_req = ExecutionRequest(
                asset=asset, direction=direction, consensus_score=consensus_score,
                signal_label=signal_label,
                execution_mode_from_consensus="AUTO" if signal_label == "STRONG_SIGNAL" else "APPROVAL",
                disagreement_gate=execution_gate, disagreement_index=disagreement_index,
                risk_flags=augmented_flags,
                risk_can_trade=risk_can_trade,
                trading_profile=trading_profile,
                open_position_count=open_count, has_position_in_asset=has_dup,
                portfolio_balance=balance,
                mean_agent_trust=mean_trust,
                system_confidence=sys_conf,
                regime=regime,
                is_exploration=is_exploration,
            )
            log.info("exploration_condition",
                     asset=asset, mode="EXPLORATION" if is_exploration else "STRICT",
                     score=consensus_score, open_positions=open_count,
                     has_duplicate=has_dup, sys_confidence=round(sys_conf, 3),
                     mean_trust=round(mean_trust, 2), regime=regime)

            decision = execution_policy.evaluate(exec_req)

            log.info("exploration_condition",
                     asset=asset, allowed=decision.allowed, mode=decision.mode,
                     reason=decision.reason, blockers=decision.blockers,
                     warnings=decision.warnings,
                     size_mult=decision.position_size_multiplier,
                     is_exploration=is_exploration)

            if not decision.allowed:
                # ── DYNAMIC REALLOCATION: if blocked by MAX_POSITIONS, try upgrading ──
                is_max_pos_block = any("MAX_POSITIONS" in b for b in decision.blockers)
                if is_max_pos_block and signal_label in ("STRONG_SIGNAL", "SIGNAL"):
                    try:
                        from bahamut.portfolio.allocator import evaluate_reallocation, execute_reallocation
                        realloc = evaluate_reallocation(
                            proposed_asset=asset,
                            proposed_direction=direction,
                            consensus_score=consensus_score,
                            signal_label=signal_label,
                            portfolio_id=pid,
                        )
                        if realloc.should_reallocate:
                            # Close weakest position
                            close_result = execute_reallocation(
                                realloc.close_position_id, realloc.reason)
                            if "error" not in close_result:
                                log.info("reallocation_complete",
                                         closed=realloc.close_asset,
                                         closed_pnl=close_result.get("pnl"),
                                         proposed=asset,
                                         margin=realloc.quality_margin)
                                # Update counts — one position closed, so retry
                                open_count -= 1
                                balance = float(conn.execute(text(
                                    "SELECT current_balance FROM paper_portfolios WHERE id = :p"
                                ), {"p": pid}).scalar() or balance)
                                # Re-evaluate policy with updated count
                                exec_req.open_position_count = open_count
                                exec_req.portfolio_balance = balance
                                decision = execution_policy.evaluate(exec_req)
                                if not decision.allowed:
                                    log.info("still_blocked_after_realloc", reason=decision.reason)
                                    return {"action": "SKIP", "reason": decision.reason,
                                            "blockers": decision.blockers,
                                            "reallocation": close_result}
                            else:
                                log.warning("realloc_close_failed", error=close_result.get("error"))
                        else:
                            log.info("realloc_rejected", reason=realloc.reason)
                    except Exception as e:
                        log.debug("realloc_attempt_failed", error=str(e))

                if not decision.allowed:
                    log.info("blocked_by_policy", reason=decision.reason, blockers=decision.blockers)
                    return {"action": "SKIP", "reason": decision.reason,
                            "blockers": decision.blockers, "policy_mode": decision.mode}

            size_mult = decision.position_size_multiplier

            # Combine with portfolio intelligence sizing
            if portfolio_size_mult < 1.0:
                size_mult *= portfolio_size_mult
                log.info("portfolio_sizing", policy_mult=decision.position_size_multiplier,
                         portfolio_mult=portfolio_size_mult, combined=size_mult)

            # Calculate SL/TP
            if atr <= 0:
                atr = entry_price * 0.01
            sl_dist = atr * 2.0
            tp_dist = atr * 3.0
            if direction == "LONG":
                sl, tp = entry_price - sl_dist, entry_price + tp_dist
            else:
                sl, tp = entry_price + sl_dist, entry_price - tp_dist

            # Position sizing with policy multiplier
            risk_amt = balance * (effective_risk_pct / 100.0)
            qty = risk_amt / sl_dist if sl_dist > 0 else 1
            pos_val = qty * entry_price
            if size_mult < 1.0:
                qty *= size_mult
                pos_val *= size_mult
                risk_amt *= size_mult

            # Insert position via canonical store
            from bahamut.paper_trading.store import open_position as store_open_position, get_position_id_by_cycle
            pos_id = store_open_position(
                portfolio_id=pid, asset=asset, direction=direction,
                entry_price=entry_price, quantity=round(qty, 6),
                position_value=round(pos_val, 2),
                entry_signal_score=consensus_score, entry_signal_label=signal_label,
                stop_loss=round(sl, 6), take_profit=round(tp, 6),
                risk_amount=round(risk_amt, 2), atr_at_entry=atr,
                consensus_score=consensus_score, agent_votes=agent_votes,
                cycle_id=cycle_id, trading_profile=trading_profile,
                regime=regime, disagreement_index=disagreement_index,
                execution_mode=decision.mode,
            )

            # Link decision trace
            if cycle_id and pos_id:
                try:
                    from bahamut.agents.persistence import link_trace_to_position
                    link_trace_to_position(cycle_id, pos_id)
                except Exception as e:
                    logger.warning("trace_link_failed", cycle_id=cycle_id, error=str(e))

            log.info("trade_opened_sync", sl=round(sl, 6), tp=round(tp, 6),
                     qty=round(qty, 6), risk=round(risk_amt, 2),
                     policy=decision.mode, size_mult=size_mult,
                     is_exploration=is_exploration)

            # Track exploration trades
            if is_exploration:
                _increment_exploration_cycle_counter()
                log.info("EXPLORATION_TRADE_OPENED",
                         asset=asset, direction=direction,
                         score=consensus_score, risk_pct=effective_risk_pct,
                         size_mult=size_mult)

            # Log portfolio state at entry for learning
            try:
                from bahamut.portfolio.learning import capture_portfolio_state, log_portfolio_decision
                entry_state = capture_portfolio_state()
                if portfolio_verdict and portfolio_verdict.scenario_risk:
                    entry_state.scenario_risk_level = portfolio_verdict.scenario_risk.get("risk_level", "")
                    entry_state.worst_case_pct = portfolio_verdict.scenario_risk.get("worst_case_pct", 0)
                if pos_id:
                    log_portfolio_decision(
                        position_id=pos_id, asset=asset, direction=direction,
                        event_type="ENTRY", state=entry_state,
                        consensus_score=consensus_score,
                        portfolio_verdict_impact=portfolio_verdict.impact_score if portfolio_verdict else 0,
                    )
            except Exception as e:
                logger.warning("portfolio_entry_log_failed", cycle_id=cycle_id, error=str(e))

            return {
                "action": "OPENED", "asset": asset, "direction": direction,
                "entry_price": entry_price, "stop_loss": round(sl, 6),
                "take_profit": round(tp, 6), "quantity": round(qty, 6),
                "risk_amount": round(risk_amt, 2), "signal_score": consensus_score,
                "policy_mode": decision.mode, "size_multiplier": size_mult,
                "policy_warnings": decision.warnings, "cycle_id": cycle_id,
            }

    except Exception as e:
        logger.error("sync_trade_failed", error=str(e), asset=asset)
        import traceback
        logger.error("sync_traceback", tb=traceback.format_exc())
        return {"action": "ERROR", "error": str(e)}


# ═══════════════════════════════════════════════════════════
# EXPLORATION MODE HELPERS
# ═══════════════════════════════════════════════════════════

EXPLORATION_CYCLE_KEY = "bahamut:exploration:cycle_count"
EXPLORATION_DAILY_KEY = "bahamut:exploration:daily_count"
EXPLORATION_COOLDOWN_KEY = "bahamut:exploration:cooldown_until"
EXPLORATION_LOSS_STREAK_KEY = "bahamut:exploration:loss_streak"
EXPLORATION_CYCLE_TTL = 180     # 3 min — one production cycle
EXPLORATION_DAILY_TTL = 86400   # 24 hours

# Configurable limits
EXPLORATION_MAX_PER_CYCLE = 1
EXPLORATION_MAX_PER_DAY = 5
EXPLORATION_MAX_POSITIONS = 2
EXPLORATION_COOLDOWN_LOSS_STREAK = 3
EXPLORATION_COOLDOWN_HOURS = 12


def _get_exploration_redis():
    try:
        import os, redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _check_exploration_eligible(
    asset: str, consensus_score: float, regime: str, signal_label: str,
) -> tuple[bool, str]:
    """
    Check if a weak signal qualifies for exploration mode.
    Returns (eligible, reason). Logs every condition for full tracing.
    """
    log = logger.bind(asset=asset, score=consensus_score)

    # 1. Config check
    try:
        from bahamut.admin.config import get_config
        enabled = get_config("exploration.enabled", True)
    except Exception:
        enabled = True

    log.info("exploration_condition",
             condition="enabled", result=enabled)
    if not enabled:
        return False, "Exploration mode disabled"

    # 2. Score floor (strategy-specific)
    min_score = 0.35
    if any(kw in asset.upper() for kw in ["BTC", "ETH"]):
        min_score = 0.40

    score_pass = consensus_score >= min_score
    log.info("exploration_condition",
             condition="score_floor", value=round(consensus_score, 4),
             required=min_score, result=score_pass)
    if not score_pass:
        return False, f"Score {consensus_score:.3f} < exploration floor {min_score}"

    # 3. Regime gate
    regime_pass = regime != "CRISIS"
    log.info("exploration_condition",
             condition="regime_not_crisis", regime=regime, result=regime_pass)
    if not regime_pass:
        return False, "CRISIS regime blocks exploration"

    # 4. Must have a directional signal
    dir_pass = signal_label != "NO_TRADE"
    log.info("exploration_condition",
             condition="has_direction", label=signal_label, result=dir_pass)
    if not dir_pass:
        return False, "NO_TRADE -- no direction to explore"

    r = _get_exploration_redis()

    # 5. Loss-streak cooldown check
    cooldown_active = False
    if r:
        try:
            cooldown_until = r.get(EXPLORATION_COOLDOWN_KEY)
            if cooldown_until:
                from datetime import datetime, timezone
                cd_time = datetime.fromisoformat(cooldown_until.decode())
                now = datetime.now(timezone.utc)
                if now < cd_time:
                    remaining = (cd_time - now).total_seconds() / 3600
                    cooldown_active = True
                    log.info("exploration_condition",
                             condition="cooldown_active", remaining_hours=round(remaining, 1),
                             result=False)
                    return False, f"Cooldown active ({remaining:.1f}h remaining after {EXPLORATION_COOLDOWN_LOSS_STREAK} losses)"
                else:
                    r.delete(EXPLORATION_COOLDOWN_KEY)
                    r.delete(EXPLORATION_LOSS_STREAK_KEY)
        except Exception:
            pass
    log.info("exploration_condition",
             condition="cooldown_active", result=not cooldown_active)

    # 6. Per-cycle limit
    cycle_count = 0
    if r:
        try:
            cycle_count = int(r.get(EXPLORATION_CYCLE_KEY) or 0)
        except Exception:
            pass
    cycle_pass = cycle_count < EXPLORATION_MAX_PER_CYCLE
    log.info("exploration_condition",
             condition="cycle_limit", current=cycle_count,
             max=EXPLORATION_MAX_PER_CYCLE, result=cycle_pass)
    if not cycle_pass:
        return False, f"Exploration cycle limit reached ({cycle_count}/{EXPLORATION_MAX_PER_CYCLE})"

    # 7. Daily limit
    daily_count = 0
    if r:
        try:
            daily_count = int(r.get(EXPLORATION_DAILY_KEY) or 0)
        except Exception:
            pass
    daily_pass = daily_count < EXPLORATION_MAX_PER_DAY
    log.info("exploration_condition",
             condition="daily_limit", current=daily_count,
             max=EXPLORATION_MAX_PER_DAY, result=daily_pass)
    if not daily_pass:
        return False, f"Daily exploration limit reached ({daily_count}/{EXPLORATION_MAX_PER_DAY})"

    # 8. Max open exploration positions
    open_exp = 0
    try:
        from bahamut.paper_trading.store import count_exploration_positions
        open_exp = count_exploration_positions()
    except Exception:
        pass
    pos_pass = open_exp < EXPLORATION_MAX_POSITIONS
    log.info("exploration_condition",
             condition="open_positions", current=open_exp,
             max=EXPLORATION_MAX_POSITIONS, result=pos_pass)
    if not pos_pass:
        return False, f"Max exploration positions open ({open_exp}/{EXPLORATION_MAX_POSITIONS})"

    log.info("exploration_condition",
             asset=asset, score=round(consensus_score, 4))
    return True, f"Exploration eligible: score={consensus_score:.3f} label={signal_label}"


def _increment_exploration_cycle_counter():
    """Increment per-cycle exploration trade counter in Redis."""
    r = _get_exploration_redis()
    if not r:
        return
    try:
        r.incr(EXPLORATION_CYCLE_KEY)
        r.expire(EXPLORATION_CYCLE_KEY, EXPLORATION_CYCLE_TTL)
        # Also increment daily counter
        r.incr(EXPLORATION_DAILY_KEY)
        # Set TTL only if new key (don't reset on increment)
        if r.ttl(EXPLORATION_DAILY_KEY) < 0:
            r.expire(EXPLORATION_DAILY_KEY, EXPLORATION_DAILY_TTL)
    except Exception:
        pass


def record_exploration_outcome(pnl: float):
    """
    Called when an exploration trade closes.
    Tracks loss streak and activates cooldown if needed.
    """
    r = _get_exploration_redis()
    if not r:
        return
    try:
        if pnl < 0:
            streak = r.incr(EXPLORATION_LOSS_STREAK_KEY)
            r.expire(EXPLORATION_LOSS_STREAK_KEY, EXPLORATION_DAILY_TTL)
            if int(streak) >= EXPLORATION_COOLDOWN_LOSS_STREAK:
                from datetime import datetime, timezone, timedelta
                cooldown_end = datetime.now(timezone.utc) + timedelta(hours=EXPLORATION_COOLDOWN_HOURS)
                r.set(EXPLORATION_COOLDOWN_KEY, cooldown_end.isoformat(), ex=EXPLORATION_COOLDOWN_HOURS * 3600 + 60)
                logger.warning("exploration_cooldown_activated",
                               streak=int(streak), cooldown_hours=EXPLORATION_COOLDOWN_HOURS)
        else:
            # Win resets streak
            r.set(EXPLORATION_LOSS_STREAK_KEY, 0, ex=EXPLORATION_DAILY_TTL)
    except Exception:
        pass


def get_exploration_status() -> dict:
    """Get exploration status for dashboard API."""
    r = _get_exploration_redis()
    status = {
        "enabled": True,
        "cycle_count": 0,
        "daily_count": 0,
        "daily_limit": EXPLORATION_MAX_PER_DAY,
        "open_positions": 0,
        "max_positions": EXPLORATION_MAX_POSITIONS,
        "loss_streak": 0,
        "cooldown_active": False,
        "cooldown_remaining_hours": 0,
    }

    try:
        from bahamut.admin.config import get_config
        status["enabled"] = get_config("exploration.enabled", True)
    except Exception:
        pass

    if r:
        try:
            status["cycle_count"] = int(r.get(EXPLORATION_CYCLE_KEY) or 0)
            status["daily_count"] = int(r.get(EXPLORATION_DAILY_KEY) or 0)
            status["loss_streak"] = int(r.get(EXPLORATION_LOSS_STREAK_KEY) or 0)

            cooldown_until = r.get(EXPLORATION_COOLDOWN_KEY)
            if cooldown_until:
                from datetime import datetime, timezone
                cd_time = datetime.fromisoformat(cooldown_until.decode())
                now = datetime.now(timezone.utc)
                if now < cd_time:
                    status["cooldown_active"] = True
                    status["cooldown_remaining_hours"] = round((cd_time - now).total_seconds() / 3600, 1)
        except Exception:
            pass

    try:
        from bahamut.paper_trading.store import count_exploration_positions
        status["open_positions"] = count_exploration_positions()
    except Exception:
        pass

    return status
