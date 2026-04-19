"""
Bahamut.AI Portfolio Kill Switch & Safe Mode

Portfolio-level emergency protections:
  1. Hard kill switch: block ALL new trades when tail risk extreme
  2. Safe mode: tighten all limits when fragility critical
  3. Deleveraging: recommend closing weakest positions when stress extreme

Integrates with execution policy — Risk agent remains absolute authority.
Kill switch sits between portfolio intelligence and execution policy.
"""
import time
import structlog
from dataclasses import dataclass, field
from bahamut.admin.config import get_config

logger = structlog.get_logger()

# Manual override — stored in Redis for cross-worker visibility
import time as _time
import os as _os
_OVERRIDE_TTL = 3600  # override expires after 1 hour
_REDIS_KEY = "bahamut:kill_switch:manual_override"


def _get_ks_redis():
    try:
        import redis
        return redis.from_url(
            _os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
    except Exception:
        return None


def force_resume_trading(set_by: str = "admin"):
    """Admin override: temporarily resume trading despite kill switch conditions.
    Stored in Redis so all workers see it immediately."""
    import json
    r = _get_ks_redis()
    if r:
        try:
            r.setex(_REDIS_KEY, _OVERRIDE_TTL, json.dumps({
                "active": True,
                "set_at": _time.time(),
                "set_by": set_by,
            }))
        except Exception:
            pass
    logger.warning("kill_switch_manual_override", set_by=set_by)


def force_activate_kill_switch(set_by: str = "admin"):
    """Admin override: force kill switch active (clear the resume override)."""
    r = _get_ks_redis()
    if r:
        try:
            r.delete(_REDIS_KEY)
        except Exception:
            pass
    logger.warning("kill_switch_force_activated", set_by=set_by)


def is_override_active() -> bool:
    """Check if manual override is still valid. Reads from Redis."""
    import json
    r = _get_ks_redis()
    if not r:
        return False
    try:
        raw = r.get(_REDIS_KEY)
        if not raw:
            return False
        data = json.loads(raw)
        if not data.get("active"):
            return False
        elapsed = _time.time() - data.get("set_at", 0)
        if elapsed > _OVERRIDE_TTL:
            r.delete(_REDIS_KEY)
            logger.info("kill_switch_override_expired")
            return False
        return True
    except Exception:
        return False


def _get_override_info() -> dict:
    """Get current override state for display."""
    import json
    r = _get_ks_redis()
    if not r:
        return {"active": False}
    try:
        raw = r.get(_REDIS_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"active": False}


@dataclass
class KillSwitchState:
    kill_switch_active: bool = False
    safe_mode_active: bool = False
    deleverage_recommended: bool = False
    deleverage_targets: list = field(default_factory=list)
    triggers: list = field(default_factory=list)
    effective_max_trades: int = 10
    effective_max_position_pct: float = 0.03

    def to_dict(self):
        return {
            "kill_switch_active": self.kill_switch_active,
            "safe_mode_active": self.safe_mode_active,
            "deleverage_recommended": self.deleverage_recommended,
            "deleverage_targets": self.deleverage_targets,
            "triggers": self.triggers,
            "effective_max_trades": self.effective_max_trades,
            "effective_max_position_pct": round(self.effective_max_position_pct, 4),
        }


def evaluate_kill_switch(
    weighted_tail_risk: float = 0.0,
    portfolio_fragility: float = 0.0,
    concentration_risk: float = 0.0,
    drawdown_proximity: float = 0.0,
    position_count: int = 0,
) -> KillSwitchState:
    """
    Evaluate portfolio-level emergency state.
    Called before every trade decision.
    """
    state = KillSwitchState()

    # ── 1. Hard kill switch ──
    ks_threshold = get_config("kill_switch.tail_risk_threshold", 0.25)
    if weighted_tail_risk >= ks_threshold:
        state.kill_switch_active = True
        state.triggers.append(
            f"KILL_SWITCH: weighted_tail_risk {weighted_tail_risk:.1%} >= {ks_threshold:.0%}")
        _log_event("kill_switch", f"tail_risk={weighted_tail_risk:.4f}")

    # ── 2. Fragility kill switch ──
    frag_threshold = get_config("kill_switch.fragility_threshold", 0.80)
    if portfolio_fragility >= frag_threshold:
        state.kill_switch_active = True
        state.triggers.append(
            f"KILL_SWITCH: fragility {portfolio_fragility:.2f} >= {frag_threshold:.2f}")
        _log_event("kill_switch_fragility", f"fragility={portfolio_fragility:.3f}")

    # ── 3. Combined stress kill switch ──
    combined_threshold = get_config("kill_switch.combined_stress_threshold", 0.70)
    combined_stress = (
        0.40 * min(1.0, weighted_tail_risk / 0.10)
        + 0.30 * portfolio_fragility
        + 0.20 * concentration_risk
        + 0.10 * drawdown_proximity
    )
    if combined_stress >= combined_threshold:
        state.kill_switch_active = True
        state.triggers.append(
            f"KILL_SWITCH: combined_stress {combined_stress:.2f} >= {combined_threshold:.2f}")

    # ── 4. Safe mode ──
    manual_safe = get_config("safe_mode.enabled", False)
    if manual_safe:
        state.safe_mode_active = True
        state.triggers.append("SAFE_MODE: manually enabled")
    elif not state.kill_switch_active and portfolio_fragility >= 0.60:
        state.safe_mode_active = True
        state.triggers.append(f"SAFE_MODE: fragility {portfolio_fragility:.2f} >= 0.60")

    # ── 5. Effective limits ──
    if state.kill_switch_active:
        state.effective_max_trades = 0
        state.effective_max_position_pct = 0.0
    elif state.safe_mode_active:
        state.effective_max_trades = int(get_config("safe_mode.max_concurrent_trades", 2))
        state.effective_max_position_pct = get_config("safe_mode.max_position_pct", 0.01)
    else:
        state.effective_max_trades = 5  # default BALANCED
        state.effective_max_position_pct = 0.03

    # ── 6. Deleveraging recommendation ──
    deleverage_frag = get_config("deleverage.fragility_trigger", 0.75)
    if portfolio_fragility >= deleverage_frag and position_count >= 2:
        state.deleverage_recommended = True
        max_close = int(get_config("deleverage.max_close_per_cycle", 1))
        state.deleverage_targets = _get_weakest_positions(max_close)
        if state.deleverage_targets:
            state.triggers.append(
                f"DELEVERAGE: recommend closing {len(state.deleverage_targets)} weakest positions")

    if state.kill_switch_active or state.safe_mode_active:
        logger.warning("portfolio_emergency_state",
                         kill=state.kill_switch_active, safe=state.safe_mode_active,
                         deleverage=state.deleverage_recommended,
                         triggers=len(state.triggers))

    # ── 7. CLOSE TRAINING POSITIONS on kill switch activation ──
    # When kill switch fires, force-close all open training positions.
    # This is the ONLY path that actually closes positions on emergency.
    if state.kill_switch_active:
        try:
            from bahamut.trading.engine import force_close_all_training_positions
            close_result = force_close_all_training_positions(
                reason=f"KILL_SWITCH: {state.triggers[0] if state.triggers else 'unknown'}"
            )
            if close_result["closed"] > 0:
                logger.warning("kill_switch_closed_training_positions",
                               closed=close_result["closed"],
                               errors=close_result["errors"])
                state.triggers.append(
                    f"CLOSED {close_result['closed']} training positions")
        except Exception as e:
            logger.error("kill_switch_close_training_failed", error=str(e)[:200])

    return state


def get_current_state() -> dict:
    """Get kill switch state for API/UI (without running full evaluation)."""
    try:
        from bahamut.portfolio.registry import load_portfolio_snapshot
        from bahamut.portfolio.engine import _compute_fragility
        from bahamut.portfolio.scenarios import evaluate_scenario_risk

        snap = load_portfolio_snapshot()
        bal = snap.balance if snap.balance > 0 else 100000.0

        # If no positions, portfolio is safe — no need for complex evaluation
        if snap.position_count == 0:
            state = KillSwitchState()  # all defaults = safe
            # Apply manual override check
            if is_override_active():
                state.triggers = [f"Kill switch overridden by {_get_override_info().get('set_by', 'admin')} (expires in {int(_OVERRIDE_TTL - (_time.time() - _get_override_info().get('set_at', 0)))}s)"]
            return state.to_dict()

        frag = _compute_fragility(snap, bal)

        # Quick scenario assessment for tail risk
        assessment = evaluate_scenario_risk(
            snap.positions, "NONE", "LONG", 0, 1.0, bal)

        state = evaluate_kill_switch(
            weighted_tail_risk=assessment.weighted_tail_risk,
            portfolio_fragility=frag.portfolio_fragility,
            concentration_risk=frag.concentration_risk,
            drawdown_proximity=frag.drawdown_proximity,
            position_count=snap.position_count,
        )

        # Apply manual override if admin has resumed trading
        if state.kill_switch_active and is_override_active():
            state.kill_switch_active = False
            state.triggers = [f"Kill switch overridden by {_get_override_info().get('set_by', 'admin')} (expires in {int(_OVERRIDE_TTL - (_time.time() - _get_override_info().get('set_at', 0)))}s)"]

        if state.kill_switch_active:
            logger.warning("kill_switch_evaluated_active",
                           tail_risk=float(assessment.weighted_tail_risk),
                           fragility=float(frag.portfolio_fragility),
                           concentration=float(frag.concentration_risk),
                           drawdown_proximity=float(frag.drawdown_proximity),
                           position_count=snap.position_count,
                           triggers=state.triggers)

        return state.to_dict()
    except Exception as e:
        logger.error("kill_switch_state_unavailable", error=str(e))
        # SAFE DEFAULT: If we can't evaluate, return INACTIVE.
        # Rationale: With 0 positions and 0% drawdown, activating the kill switch
        # is a false positive that blocks all trading. The portfolio manager's own
        # drawdown-based kill switch in manager.py is the last line of defense.
        return {
            "kill_switch_active": False,
            "safe_mode_active": True,
            "deleverage_recommended": False,
            "deleverage_targets": [],
            "triggers": [f"Kill switch evaluation failed ({str(e)[:100]}) — safe mode enabled as precaution"],
            "effective_max_trades": 2,
            "effective_max_position_pct": 0.01,
            "error": str(e),
            "note": "Intelligence subsystem unavailable — safe mode active, kill switch NOT triggered",
        }


def _get_weakest_positions(max_count: int) -> list[dict]:
    """Get weakest positions for deleveraging recommendation."""
    try:
        from bahamut.portfolio.allocator import get_position_rankings
        rankings = get_position_rankings()
        if not rankings:
            return []
        # Rankings are sorted desc by quality — weakest is last
        weakest = rankings[-max_count:] if len(rankings) >= max_count else rankings
        return [{"position_id": r.get("position_id"), "asset": r.get("asset"),
                 "quality": r.get("quality_score")} for r in weakest
                if r.get("quality_score", 1.0) < 0.40]
    except Exception as e:

        logger.warning("kill_switch_silent_error", error=str(e))
        return []


def _log_event(event_type: str, detail: str):
    """Log kill switch / safe mode events."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            pass  # Schema managed by db.schema.tables
            conn.execute(text("""
                INSERT INTO kill_switch_events (event_type, detail) VALUES (:e, :d)
            """), {"e": event_type, "d": detail})
            conn.commit()
    except Exception as e:
        logger.error("kill_switch_event_log_failed", event_type=event_type, error=str(e))
