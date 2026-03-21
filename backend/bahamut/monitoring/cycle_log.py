"""
Bahamut Cycle Log — records every orchestrator cycle with full detail.

Storage: Redis (fast, recent 50 cycles) with in-memory fallback.
Each cycle records: timing, status, per-asset regime, per-strategy decisions.
"""
import json
import time
import uuid
import os
import structlog
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

logger = structlog.get_logger()


@dataclass
class StrategyDecision:
    strategy: str = ""
    result: str = "NO_SIGNAL"    # NO_SIGNAL | BLOCKED | SIGNAL | EXECUTED | SKIPPED
    reason: str = ""


@dataclass
class AssetEvaluation:
    asset: str = ""
    timestamp: str = ""
    regime: str = ""
    regime_confidence: float = 0.0
    active_strategies: list = field(default_factory=list)
    strategies_evaluated: list = field(default_factory=list)
    summary: str = ""
    bar_close: float = 0.0
    new_bar: bool = False


@dataclass
class CycleRecord:
    cycle_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    status: str = "RUNNING"       # RUNNING | SUCCESS | SKIPPED | ERROR
    skip_reason: str = ""
    error: str = ""
    data_source: str = "SYNTHETIC"
    assets: list = field(default_factory=list)
    signals_generated: int = 0
    orders_created: int = 0
    positions_opened: int = 0
    positions_closed: int = 0

    def to_dict(self):
        d = asdict(self)
        # Convert nested dataclass lists
        d["assets"] = [asdict(a) if hasattr(a, "__dataclass_fields__") else a for a in self.assets]
        for ad in d["assets"]:
            if "strategies_evaluated" in ad:
                ad["strategies_evaluated"] = [
                    asdict(s) if hasattr(s, "__dataclass_fields__") else s
                    for s in ad["strategies_evaluated"]
                ]
        return d


# ═══════════════════════════════════════════════════════
# CYCLE BUILDER — used by orchestrator to build records
# ═══════════════════════════════════════════════════════

_current_cycle: CycleRecord = None


def start_cycle() -> CycleRecord:
    """Begin a new cycle record."""
    global _current_cycle

    # Detect data source
    data_src = "SYNTHETIC"
    try:
        from bahamut.ingestion.adapters.twelvedata import twelve_data
        if twelve_data.configured:
            data_src = "LIVE"
    except Exception:
        pass

    _current_cycle = CycleRecord(
        cycle_id=str(uuid.uuid4())[:8],
        started_at=datetime.now(timezone.utc).isoformat(),
        status="RUNNING",
        data_source=data_src,
    )
    return _current_cycle


def record_skip(reason: str):
    """Record that cycle was skipped (e.g. lock held)."""
    global _current_cycle
    c = CycleRecord(
        cycle_id=str(uuid.uuid4())[:8],
        started_at=datetime.now(timezone.utc).isoformat(),
        ended_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=0,
        status="SKIPPED",
        skip_reason=reason,
    )
    _current_cycle = c
    _store(c)
    return c


def add_asset_evaluation(ev: AssetEvaluation):
    """Add an asset evaluation to the current cycle."""
    if _current_cycle:
        _current_cycle.assets.append(ev)


def add_strategy_decision(asset: str, decision: StrategyDecision):
    """Add a strategy decision to the most recent asset evaluation."""
    if not _current_cycle:
        return
    for a in reversed(_current_cycle.assets):
        if a.asset == asset:
            a.strategies_evaluated.append(decision)
            return


def record_signal():
    if _current_cycle:
        _current_cycle.signals_generated += 1


def record_order():
    if _current_cycle:
        _current_cycle.orders_created += 1


def record_position_opened():
    if _current_cycle:
        _current_cycle.positions_opened += 1


def record_position_closed():
    if _current_cycle:
        _current_cycle.positions_closed += 1


def end_cycle(status: str = "SUCCESS", error: str = ""):
    """Finalize and store the current cycle."""
    global _current_cycle
    if not _current_cycle:
        return

    _current_cycle.ended_at = datetime.now(timezone.utc).isoformat()
    _current_cycle.status = status
    _current_cycle.error = error

    # Calculate duration
    try:
        t0 = datetime.fromisoformat(_current_cycle.started_at)
        t1 = datetime.fromisoformat(_current_cycle.ended_at)
        _current_cycle.duration_ms = int((t1 - t0).total_seconds() * 1000)
    except Exception:
        pass

    # Generate asset summaries
    for a in _current_cycle.assets:
        if not a.summary:
            results = [f"{s.strategy}→{s.result}" for s in a.strategies_evaluated]
            a.summary = f"{a.regime}, {', '.join(results) if results else 'no strategies evaluated'}"

    _store(_current_cycle)
    logger.info("cycle_complete",
                cycle_id=_current_cycle.cycle_id,
                status=status,
                duration_ms=_current_cycle.duration_ms,
                signals=_current_cycle.signals_generated,
                orders=_current_cycle.orders_created)


def get_current_cycle() -> dict:
    """Get current running cycle (or last completed)."""
    if _current_cycle:
        return _current_cycle.to_dict()
    return {}


# ═══════════════════════════════════════════════════════
# STORAGE — Redis with in-memory fallback
# ═══════════════════════════════════════════════════════

_history: list[dict] = []
MAX_HISTORY = 50


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _store(cycle: CycleRecord):
    """Store cycle in Redis and in-memory."""
    d = cycle.to_dict()
    _history.insert(0, d)
    if len(_history) > MAX_HISTORY:
        _history.pop()

    r = _get_redis()
    if r:
        try:
            r.lpush("bahamut:cycle_log", json.dumps(d))
            r.ltrim("bahamut:cycle_log", 0, MAX_HISTORY - 1)
            # Update counters
            if cycle.status == "SKIPPED":
                r.incr("bahamut:cycles_skipped")
            elif cycle.status == "ERROR":
                r.incr("bahamut:cycles_errored")
            r.set("bahamut:last_cycle", json.dumps(d))
        except Exception:
            pass


def get_cycle_history(limit: int = 20) -> list[dict]:
    """Get recent cycle history."""
    r = _get_redis()
    if r:
        try:
            raw = r.lrange("bahamut:cycle_log", 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception:
            pass
    return _history[:limit]


def get_last_cycle() -> dict:
    """Get the last completed cycle with full detail."""
    r = _get_redis()
    if r:
        try:
            raw = r.get("bahamut:last_cycle")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _history[0] if _history else {}


def get_cycle_stats() -> dict:
    """Get rolling cycle statistics."""
    history = get_cycle_history(50)
    if not history:
        return {"total": 0, "success": 0, "skipped": 0, "errors": 0, "avg_duration_ms": 0}

    success = len([c for c in history if c.get("status") == "SUCCESS"])
    skipped = len([c for c in history if c.get("status") == "SKIPPED"])
    errors = len([c for c in history if c.get("status") == "ERROR"])
    durations = [c.get("duration_ms", 0) for c in history if c.get("duration_ms", 0) > 0]

    return {
        "total": len(history),
        "success": success,
        "skipped": skipped,
        "errors": errors,
        "avg_duration_ms": round(sum(durations) / max(1, len(durations))),
        "last_success_at": next(
            (c.get("ended_at") for c in history if c.get("status") == "SUCCESS"), None),
    }
