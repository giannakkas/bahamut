"""
Bahamut.AI — Adaptive Thresholds Engine

Self-adjusting execution parameters for the TRAINING engine.
Bounded, deterministic, auditable, and safe.

Pipeline:
  1. Compute rolling metrics from last N closed training trades
  2. Choose mode: CONSERVATIVE / BALANCED / AGGRESSIVE
  3. Map mode → threshold profile (within hard bounds)
  4. Apply incremental adjustment (no big jumps)
  5. Persist state + audit log to Redis
  6. Consumers (selector, engine) read current profile

TRAINING ONLY — does not touch production.
"""
import json
import os
import structlog
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# HARD SAFETY BOUNDS — NEVER EXCEEDED
# ═══════════════════════════════════════════

BOUNDS = {
    "standard_threshold":       {"default": 80, "min": 75, "max": 90},
    "early_threshold":          {"default": 92, "min": 88, "max": 97},
    "max_early_per_cycle":      {"default": 1,  "min": 0,  "max": 3},
    "early_risk_multiplier":    {"default": 0.5, "min": 0.25, "max": 1.0},
}

# ═══════════════════════════════════════════
# MODE DEFINITIONS
# ═══════════════════════════════════════════

MODE_PROFILES = {
    "CONSERVATIVE": {
        "standard_threshold": 85,
        "early_threshold": 95,
        "max_early_per_cycle": 0,     # Early execution disabled
        "early_risk_multiplier": 0.25,
    },
    "BALANCED": {
        "standard_threshold": 80,
        "early_threshold": 92,
        "max_early_per_cycle": 1,
        "early_risk_multiplier": 0.5,
    },
    "AGGRESSIVE": {
        "standard_threshold": 76,
        "early_threshold": 89,
        "max_early_per_cycle": 2,
        "early_risk_multiplier": 0.75,
    },
}

# ═══════════════════════════════════════════
# ADAPTATION POLICY
# ═══════════════════════════════════════════

POLICY = {
    "min_samples": 20,             # No adaptation below this
    "rolling_window": 50,          # Last N trades for metrics
    "short_window": 20,            # Recent performance window
    "cooldown_trades": 10,         # Min trades between adjustments
    "max_step_per_param": {        # Max change per adjustment
        "standard_threshold": 3,
        "early_threshold": 3,
        "max_early_per_cycle": 1,
        "early_risk_multiplier": 0.15,
    },
    # Thresholds for mode selection
    "conservative_triggers": {
        "win_rate_below": 0.35,
        "profit_factor_below": 0.8,
        "drawdown_pct_above": 5.0,
        "stop_out_rate_above": 0.5,
    },
    "aggressive_triggers": {
        "win_rate_above": 0.55,
        "profit_factor_above": 1.5,
        "drawdown_pct_below": 1.0,
        "stop_out_rate_below": 0.2,
    },
}

REDIS_KEY_PROFILE = "bahamut:training:adaptive:profile"
REDIS_KEY_HISTORY = "bahamut:training:adaptive:history"
REDIS_KEY_METRICS = "bahamut:training:adaptive:last_metrics"


# ═══════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════

@dataclass
class ThresholdProfile:
    mode: str                          # WARMING_UP / CONSERVATIVE / BALANCED / AGGRESSIVE
    standard_threshold: int
    early_threshold: int
    max_early_per_cycle: int
    early_risk_multiplier: float
    early_execution_enabled: bool
    last_adjustment_time: str
    last_adjustment_reason: str
    trades_since_last_adjustment: int
    total_samples: int

    @staticmethod
    def default():
        return ThresholdProfile(
            mode="WARMING_UP",
            standard_threshold=BOUNDS["standard_threshold"]["default"],
            early_threshold=BOUNDS["early_threshold"]["default"],
            max_early_per_cycle=BOUNDS["max_early_per_cycle"]["default"],
            early_risk_multiplier=BOUNDS["early_risk_multiplier"]["default"],
            early_execution_enabled=False,
            last_adjustment_time="",
            last_adjustment_reason="Waiting for minimum samples",
            trades_since_last_adjustment=0,
            total_samples=0,
        )


@dataclass
class RollingMetrics:
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    avg_pnl: float
    drawdown_pct: float
    stop_out_rate: float
    early_win_rate: float
    standard_win_rate: float
    early_count: int
    standard_count: int
    recent_win_rate: float         # Short window
    recent_profit_factor: float


# ═══════════════════════════════════════════
# COMPUTE ROLLING METRICS
# ═══════════════════════════════════════════

def compute_rolling_metrics() -> RollingMetrics:
    """Compute performance metrics from recent closed training trades."""
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT pnl, exit_reason, execution_type, bars_held
            FROM training_trades
            ORDER BY created_at DESC
            LIMIT :n
        """, {"n": POLICY["rolling_window"]})
    except Exception:
        rows = []

    if not rows:
        return RollingMetrics(
            total_trades=0, win_rate=0, profit_factor=0, expectancy=0,
            avg_pnl=0, drawdown_pct=0, stop_out_rate=0,
            early_win_rate=0, standard_win_rate=0,
            early_count=0, standard_count=0,
            recent_win_rate=0, recent_profit_factor=0,
        )

    total = len(rows)
    wins = sum(1 for r in rows if float(r.get("pnl", 0) or 0) > 0)
    gross_profit = sum(float(r.get("pnl", 0) or 0) for r in rows if float(r.get("pnl", 0) or 0) > 0)
    gross_loss = abs(sum(float(r.get("pnl", 0) or 0) for r in rows if float(r.get("pnl", 0) or 0) < 0))
    total_pnl = sum(float(r.get("pnl", 0) or 0) for r in rows)
    stop_outs = sum(1 for r in rows if r.get("exit_reason") == "SL")

    # Early vs standard
    early_rows = [r for r in rows if r.get("execution_type") == "early"]
    std_rows = [r for r in rows if r.get("execution_type") != "early"]
    early_wins = sum(1 for r in early_rows if float(r.get("pnl", 0) or 0) > 0)
    std_wins = sum(1 for r in std_rows if float(r.get("pnl", 0) or 0) > 0)

    # Drawdown: peak-to-trough of cumulative PnL
    cum = 0
    peak = 0
    max_dd = 0
    for r in reversed(rows):  # Oldest first
        cum += float(r.get("pnl", 0) or 0)
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Short window
    short = rows[:POLICY["short_window"]]
    short_total = len(short)
    short_wins = sum(1 for r in short if float(r.get("pnl", 0) or 0) > 0)
    short_gp = sum(float(r.get("pnl", 0) or 0) for r in short if float(r.get("pnl", 0) or 0) > 0)
    short_gl = abs(sum(float(r.get("pnl", 0) or 0) for r in short if float(r.get("pnl", 0) or 0) < 0))

    return RollingMetrics(
        total_trades=total,
        win_rate=round(wins / max(1, total), 4),
        profit_factor=round(gross_profit / max(gross_loss, 0.01), 2),
        expectancy=round(total_pnl / max(1, total), 2),
        avg_pnl=round(total_pnl / max(1, total), 2),
        drawdown_pct=round(max_dd / max(1, abs(peak)) * 100 if peak > 0 else 0, 2),
        stop_out_rate=round(stop_outs / max(1, total), 4),
        early_win_rate=round(early_wins / max(1, len(early_rows)), 4),
        standard_win_rate=round(std_wins / max(1, len(std_rows)), 4),
        early_count=len(early_rows),
        standard_count=len(std_rows),
        recent_win_rate=round(short_wins / max(1, short_total), 4),
        recent_profit_factor=round(short_gp / max(short_gl, 0.01), 2),
    )


# ═══════════════════════════════════════════
# MODE SELECTION
# ═══════════════════════════════════════════

def choose_mode(metrics: RollingMetrics) -> str:
    """Deterministic mode selection from rolling metrics."""
    ct = POLICY["conservative_triggers"]
    at = POLICY["aggressive_triggers"]

    # Conservative triggers (any one is enough)
    if (metrics.win_rate < ct["win_rate_below"] or
        metrics.profit_factor < ct["profit_factor_below"] or
        metrics.drawdown_pct > ct["drawdown_pct_above"] or
        metrics.stop_out_rate > ct["stop_out_rate_above"]):
        return "CONSERVATIVE"

    # Aggressive triggers (ALL required)
    if (metrics.win_rate > at["win_rate_above"] and
        metrics.profit_factor > at["profit_factor_above"] and
        metrics.drawdown_pct < at["drawdown_pct_below"] and
        metrics.stop_out_rate < at["stop_out_rate_below"]):
        return "AGGRESSIVE"

    return "BALANCED"


# ═══════════════════════════════════════════
# COMPUTE THRESHOLD UPDATES
# ═══════════════════════════════════════════

def compute_threshold_updates(
    current: ThresholdProfile,
    target_mode: str,
    metrics: RollingMetrics,
) -> ThresholdProfile:
    """Compute new profile with incremental bounded adjustments."""
    target = MODE_PROFILES[target_mode]
    max_step = POLICY["max_step_per_param"]

    new = ThresholdProfile(
        mode=target_mode,
        standard_threshold=_step_toward(
            current.standard_threshold, target["standard_threshold"],
            max_step["standard_threshold"],
            BOUNDS["standard_threshold"]["min"], BOUNDS["standard_threshold"]["max"]),
        early_threshold=_step_toward(
            current.early_threshold, target["early_threshold"],
            max_step["early_threshold"],
            BOUNDS["early_threshold"]["min"], BOUNDS["early_threshold"]["max"]),
        max_early_per_cycle=_step_toward(
            current.max_early_per_cycle, target["max_early_per_cycle"],
            max_step["max_early_per_cycle"],
            BOUNDS["max_early_per_cycle"]["min"], BOUNDS["max_early_per_cycle"]["max"]),
        early_risk_multiplier=round(_step_toward_float(
            current.early_risk_multiplier, target["early_risk_multiplier"],
            max_step["early_risk_multiplier"],
            BOUNDS["early_risk_multiplier"]["min"], BOUNDS["early_risk_multiplier"]["max"]), 2),
        early_execution_enabled=target_mode != "CONSERVATIVE",
        last_adjustment_time=datetime.now(timezone.utc).isoformat(),
        last_adjustment_reason=_build_reason(current.mode, target_mode, metrics),
        trades_since_last_adjustment=0,
        total_samples=metrics.total_trades,
    )

    return new


def _step_toward(current: int, target: int, max_step: int, lo: int, hi: int) -> int:
    """Move current toward target by at most max_step, clamped to bounds."""
    diff = target - current
    step = max(-max_step, min(max_step, diff))
    return max(lo, min(hi, current + step))


def _step_toward_float(current: float, target: float, max_step: float, lo: float, hi: float) -> float:
    diff = target - current
    step = max(-max_step, min(max_step, diff))
    return max(lo, min(hi, current + step))


def _build_reason(old_mode: str, new_mode: str, m: RollingMetrics) -> str:
    if old_mode == new_mode:
        return f"Staying {new_mode}: WR={m.win_rate:.0%} PF={m.profit_factor:.1f} DD={m.drawdown_pct:.1f}%"
    return f"{old_mode} → {new_mode}: WR={m.win_rate:.0%} PF={m.profit_factor:.1f} DD={m.drawdown_pct:.1f}% SO={m.stop_out_rate:.0%}"


# ═══════════════════════════════════════════
# STATE PERSISTENCE (Redis)
# ═══════════════════════════════════════════

def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def get_current_profile() -> ThresholdProfile:
    """Get current adaptive threshold profile from Redis (or defaults)."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(REDIS_KEY_PROFILE)
            if raw:
                d = json.loads(raw)
                return ThresholdProfile(**d)
        except Exception:
            pass
    return ThresholdProfile.default()


def persist_profile(profile: ThresholdProfile):
    """Save profile to Redis."""
    r = _get_redis()
    if not r:
        return
    try:
        r.set(REDIS_KEY_PROFILE, json.dumps(asdict(profile)))
    except Exception:
        pass


def _append_audit(old: ThresholdProfile, new: ThresholdProfile, metrics: RollingMetrics):
    """Append adjustment to audit history (Redis list, last 50)."""
    r = _get_redis()
    if not r:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_mode": old.mode,
            "new_mode": new.mode,
            "old_standard_threshold": old.standard_threshold,
            "new_standard_threshold": new.standard_threshold,
            "old_early_threshold": old.early_threshold,
            "new_early_threshold": new.early_threshold,
            "old_max_early": old.max_early_per_cycle,
            "new_max_early": new.max_early_per_cycle,
            "old_risk_mult": old.early_risk_multiplier,
            "new_risk_mult": new.early_risk_multiplier,
            "early_enabled": new.early_execution_enabled,
            "reason": new.last_adjustment_reason,
            "metrics": asdict(metrics),
        }
        r.lpush(REDIS_KEY_HISTORY, json.dumps(entry))
        r.ltrim(REDIS_KEY_HISTORY, 0, 49)  # Keep last 50
    except Exception:
        pass


def persist_metrics(metrics: RollingMetrics):
    """Save latest metrics snapshot to Redis."""
    r = _get_redis()
    if r:
        try:
            r.set(REDIS_KEY_METRICS, json.dumps(asdict(metrics)), ex=1800)
        except Exception:
            pass


def get_last_metrics() -> dict:
    """Get last metrics snapshot."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(REDIS_KEY_METRICS)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return {}


def get_adjustment_history() -> list[dict]:
    """Get last 20 adjustment audit entries."""
    r = _get_redis()
    if r:
        try:
            raw_list = r.lrange(REDIS_KEY_HISTORY, 0, 19)
            return [json.loads(x) for x in raw_list] if raw_list else []
        except Exception:
            pass
    return []


# ═══════════════════════════════════════════
# MAIN ENTRY POINT — called after each training cycle
# ═══════════════════════════════════════════

def run_adaptive_update() -> ThresholdProfile:
    """
    Main adaptive loop. Called after training cycle completes.

    Returns the current (possibly updated) profile.
    """
    current = get_current_profile()
    metrics = compute_rolling_metrics()
    persist_metrics(metrics)

    # 1. Not enough samples → stay in WARMING_UP
    if metrics.total_trades < POLICY["min_samples"]:
        if current.mode != "WARMING_UP":
            current.mode = "WARMING_UP"
            current.last_adjustment_reason = f"Only {metrics.total_trades}/{POLICY['min_samples']} samples"
            current.total_samples = metrics.total_trades
            persist_profile(current)
        return current

    # 2. Cooldown check
    current.trades_since_last_adjustment += 1
    if current.trades_since_last_adjustment < POLICY["cooldown_trades"]:
        current.total_samples = metrics.total_trades
        persist_profile(current)
        return current

    # 3. Choose target mode
    target_mode = choose_mode(metrics)

    # 4. Compute incremental update
    new_profile = compute_threshold_updates(current, target_mode, metrics)

    # 5. Emergency: if performance is very bad, force conservative
    if metrics.win_rate < 0.25 or metrics.drawdown_pct > 10.0:
        new_profile.mode = "CONSERVATIVE"
        new_profile.early_execution_enabled = False
        new_profile.max_early_per_cycle = 0
        new_profile.standard_threshold = min(BOUNDS["standard_threshold"]["max"],
                                              new_profile.standard_threshold + 3)
        new_profile.last_adjustment_reason = f"EMERGENCY: WR={metrics.win_rate:.0%} DD={metrics.drawdown_pct:.1f}%"

    # 6. Audit + persist
    _append_audit(current, new_profile, metrics)
    persist_profile(new_profile)

    logger.info("adaptive_threshold_updated",
                mode=new_profile.mode,
                std_thresh=new_profile.standard_threshold,
                early_thresh=new_profile.early_threshold,
                early_enabled=new_profile.early_execution_enabled,
                reason=new_profile.last_adjustment_reason)

    return new_profile
