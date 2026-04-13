"""
Bahamut Training Engine — Paper-only execution for the training universe.

COMPLETELY ISOLATED from production ExecutionEngine.
Stores state in Redis (cross-process) and DB (durable history).
Feeds the learning engine with every closed trade.

Position lifecycle:
  signal → open position (Redis) → bar update → SL/TP/timeout close → DB + learning
"""
import json
import os
import uuid
import structlog
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = structlog.get_logger()

REDIS_KEY_POSITIONS = "bahamut:training:positions"
REDIS_KEY_STATS = "bahamut:training:stats"
REDIS_KEY_RECENT = "bahamut:training:recent_trades"


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


# ═══════════════════════════════════════════
# POSITION MODEL
# ═══════════════════════════════════════════

@dataclass
class TrainingPosition:
    position_id: str
    asset: str
    asset_class: str
    strategy: str
    direction: str       # LONG / SHORT
    entry_price: float
    stop_price: float
    tp_price: float
    size: float          # virtual units
    risk_amount: float   # virtual dollars at risk
    entry_time: str
    bars_held: int = 0
    max_hold_bars: int = 30
    current_price: float = 0.0
    execution_type: str = "standard"      # "standard" | "early"
    confidence_score: float = 0.0
    trigger_reason: str = "4h_close"      # "4h_close" | "early_signal"
    regime: str = ""                      # TREND / RANGE / BREAKOUT — preserved for learning
    exchange_order_id: str = ""           # Binance/Alpaca order ID
    execution_platform: str = "internal"  # "binance" | "alpaca" | "internal"

    @property
    def unrealized_pnl(self):
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.size
        return (self.entry_price - self.current_price) * self.size


@dataclass
class TrainingTrade:
    trade_id: str
    position_id: str
    asset: str
    asset_class: str
    strategy: str
    direction: str
    entry_price: float
    exit_price: float
    stop_price: float
    tp_price: float
    size: float
    risk_amount: float
    pnl: float
    pnl_pct: float
    entry_time: str
    exit_time: str
    exit_reason: str     # SL / TP / TIMEOUT / MANUAL
    bars_held: int
    regime: str = ""
    execution_type: str = "standard"
    confidence_score: float = 0.0
    trigger_reason: str = "4h_close"
    exchange_order_id: str = ""           # Binance/Alpaca order ID
    execution_platform: str = "internal"  # "binance" | "alpaca" | "internal"


# ═══════════════════════════════════════════
# POSITION MANAGEMENT (DB-backed + Redis cache)
# DB is the canonical source. Redis is a fast cache.
# On load: try Redis first (fast), reconcile from DB if mismatch.
# On write: always write to BOTH.
# ═══════════════════════════════════════════

def _load_positions() -> list[TrainingPosition]:
    """Load all open training positions. Redis first, DB fallback."""
    # Try Redis (fast path)
    r = _get_redis()
    if r:
        try:
            raw = r.hgetall(REDIS_KEY_POSITIONS)
            if raw:
                positions = []
                for v in raw.values():
                    d = json.loads(v)
                    positions.append(TrainingPosition(**d))
                return positions
        except Exception as e:
            logger.warning("training_load_positions_redis_failed", error=str(e))

    # Redis empty or failed — load from DB (canonical source)
    return _load_positions_from_db()


def _load_positions_from_db() -> list[TrainingPosition]:
    """Load open positions from DB. Repopulates Redis cache."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT position_id, asset, asset_class, strategy, direction,
                       entry_price, stop_price, tp_price, size, risk_amount,
                       entry_time, bars_held, max_hold_bars, current_price,
                       execution_type, confidence_score, trigger_reason
                FROM training_positions WHERE status = 'OPEN'
            """)).mappings().all()

            positions = []
            for row in rows:
                pos = TrainingPosition(
                    position_id=row["position_id"],
                    asset=row["asset"],
                    asset_class=row["asset_class"] or "unknown",
                    strategy=row["strategy"],
                    direction=row["direction"],
                    entry_price=float(row["entry_price"]),
                    stop_price=float(row["stop_price"]),
                    tp_price=float(row["tp_price"]),
                    size=float(row["size"]),
                    risk_amount=float(row["risk_amount"]),
                    entry_time=str(row["entry_time"] or ""),
                    bars_held=int(row["bars_held"] or 0),
                    max_hold_bars=int(row["max_hold_bars"] or 30),
                    current_price=float(row["current_price"] or 0),
                    execution_type=str(row["execution_type"] or "standard"),
                    confidence_score=float(row["confidence_score"] or 0),
                    trigger_reason=str(row["trigger_reason"] or "4h_close"),
                )
                positions.append(pos)

            # Repopulate Redis cache from DB
            if positions:
                r = _get_redis()
                if r:
                    try:
                        r.delete(REDIS_KEY_POSITIONS)
                        for pos in positions:
                            r.hset(REDIS_KEY_POSITIONS, pos.position_id, json.dumps(asdict(pos)))
                    except Exception:
                        pass

            logger.info("training_positions_loaded_from_db", count=len(positions))
            return positions
    except Exception as e:
        logger.error("training_load_positions_db_failed", error=str(e))
        return []


def _save_position(pos: TrainingPosition):
    """Save a position to Redis + DB (dual write)."""
    # Redis (fast cache)
    r = _get_redis()
    if r:
        try:
            r.hset(REDIS_KEY_POSITIONS, pos.position_id, json.dumps(asdict(pos)))
        except Exception:
            pass

    # DB (canonical)
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO training_positions
                (position_id, asset, asset_class, strategy, direction,
                 entry_price, stop_price, tp_price, size, risk_amount,
                 entry_time, bars_held, max_hold_bars, current_price,
                 execution_type, confidence_score, trigger_reason, status)
                VALUES (:pid, :a, :ac, :s, :d, :ep, :sp, :tp, :sz, :ra,
                        :et, :bh, :mhb, :cp, :ext, :cs, :tr, 'OPEN')
                ON CONFLICT (position_id) DO UPDATE SET
                    bars_held = EXCLUDED.bars_held,
                    current_price = EXCLUDED.current_price,
                    status = 'OPEN'
            """), {
                "pid": pos.position_id, "a": pos.asset, "ac": pos.asset_class,
                "s": pos.strategy, "d": pos.direction,
                "ep": pos.entry_price, "sp": pos.stop_price,
                "tp": pos.tp_price, "sz": pos.size, "ra": pos.risk_amount,
                "et": pos.entry_time, "bh": pos.bars_held,
                "mhb": pos.max_hold_bars, "cp": pos.current_price,
                "ext": pos.execution_type, "cs": pos.confidence_score,
                "tr": pos.trigger_reason,
            })
            conn.commit()
    except Exception as e:
        logger.error("training_save_position_db_failed",
                     position_id=pos.position_id, error=str(e))


def _remove_position(position_id: str) -> bool:
    """Remove a closed position from Redis + mark CLOSED in DB.
    Returns True if position was actually removed (first caller wins).
    Returns False if already removed (duplicate close attempt)."""
    removed = False

    # Redis: hdel returns count of keys removed — 0 means already gone
    r = _get_redis()
    if r:
        try:
            count = r.hdel(REDIS_KEY_POSITIONS, position_id)
            removed = count > 0
        except Exception:
            pass

    if not removed:
        # Position wasn't in Redis — already closed by another call
        return False

    # DB: mark as CLOSED (don't delete — keep for audit)
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text(
                "UPDATE training_positions SET status = 'CLOSED' WHERE position_id = :pid"
            ), {"pid": position_id})
            conn.commit()
    except Exception as e:
        logger.error("training_remove_position_db_failed",
                     position_id=position_id, error=str(e))

    return True


def get_open_position_count() -> int:
    """Get count of open training positions. Redis first, DB fallback."""
    r = _get_redis()
    if r:
        try:
            count = r.hlen(REDIS_KEY_POSITIONS)
            if count and count > 0:
                return count
        except Exception:
            pass
    # DB fallback
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM training_positions WHERE status = 'OPEN'"
            )).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


# ═══════════════════════════════════════════
# OPEN NEW POSITION
# ═══════════════════════════════════════════

def open_training_position(
    asset: str,
    asset_class: str,
    strategy: str,
    direction: str,
    entry_price: float,
    sl_pct: float,
    tp_pct: float,
    risk_amount: float,
    regime: str = "",
    max_hold_bars: int = 30,
    execution_type: str = "standard",
    confidence_score: float = 0.0,
    trigger_reason: str = "4h_close",
) -> TrainingPosition | None:
    """Open a new training position. Returns the position or None if rejected."""
    from bahamut.config_assets import TRAINING_MAX_POSITIONS

    # ═══════════════════════════════════════════
    # ENGINE-LEVEL SUPPRESS MAP — catches ALL signal paths
    # This is the single choke point every trade must pass through.
    # Strategy.evaluate(), debug_exploration, and CRASH SHORT all converge here.
    # ═══════════════════════════════════════════
    # ═══════════════════════════════════════════
    # ENGINE-LEVEL SUPPRESS MAP — catches ALL signal paths
    # Single canonical source: config_assets.TRAINING_SUPPRESS
    # ═══════════════════════════════════════════
    from bahamut.config_assets import TRAINING_SUPPRESS
    global_block = TRAINING_SUPPRESS.get("*", set())
    strat_block = TRAINING_SUPPRESS.get(strategy, set())
    if asset in global_block or asset in strat_block:
        logger.info("training_engine_suppressed",
                    asset=asset, strategy=strategy, direction=direction,
                    reason="ENGINE_SUPPRESS_MAP")
        _increment_counter(_get_redis(), "bahamut:counters:engine_suppress_blocks")
        return None

    # Check position limit
    current_count = get_open_position_count()
    if current_count >= TRAINING_MAX_POSITIONS:
        logger.warning("training_position_rejected",
                       asset=asset, reason="POSITION_LIMIT",
                       current=current_count, max=TRAINING_MAX_POSITIONS)
        return None

    # Check no duplicate — two layers:
    # 1. In-process set for same-cycle race condition
    # 2. DB positions for cross-cycle dedup
    _opened_this_cycle: set = getattr(open_training_position, "_opened_this_cycle", set())
    dedup_key = f"{asset}:{strategy}:{direction}"
    asset_key = f"ASSET:{asset}"
    if dedup_key in _opened_this_cycle or asset_key in _opened_this_cycle:
        logger.warning("training_position_rejected",
                       asset=asset, reason="DUPLICATE_SAME_CYCLE",
                       strategy=strategy, direction=direction)
        return None

    existing = _load_positions()
    for p in existing:
        if p.asset == asset:
            logger.warning("training_position_rejected",
                           asset=asset, reason="DUPLICATE_ASSET",
                           strategy=strategy, direction=direction,
                           existing_strategy=p.strategy, existing_direction=p.direction)
            return None

    # Per-asset cooldown: skip if recently closed (avoid repeated entries on same asset)
    # v5_base gets 2hr cooldown (20-bar hold on 15m = 5hr, so 2hr gap between attempts)
    # Others get 30min (default)
    COOLDOWN_BY_STRATEGY = {
        "v5_base": 14400,       # 4 hours — long-hold strategy needs longer gap
    }
    COOLDOWN_DEFAULT = 1800    # 30 minutes
    try:
        r = _get_redis()
        if r:
            # Check both asset-level and asset+strategy-level cooldowns
            cooldown_key = f"bahamut:training:cooldown:{asset}"
            cooldown_key_strat = f"bahamut:training:cooldown:{asset}:{strategy}"
            if r.exists(cooldown_key) or r.exists(cooldown_key_strat):
                logger.info("training_position_rejected_cooldown",
                            asset=asset, strategy=strategy, direction=direction,
                            reason="Asset on cooldown after recent close")
                return None
    except Exception:
        pass

    # Entry price sanity check — reject obviously wrong prices
    # (e.g. BTC price leaking into EURUSD)
    PRICE_SANITY = {
        "forex": (0.001, 300),         # EURUSD ~1.08, USDJPY ~150
        "crypto": (0.0001, 200000),    # XRP ~2, BTC ~85K
        "stock": (1, 100000),          # AAPL ~220, BRK.A ~600K
        "commodity": (0.5, 15000),     # Gold ~3100, Oil ~70
        "index": (100, 25000),          # SPX ~5600, IXIC ~17K, DJI ~40K
    }
    limits = PRICE_SANITY.get(asset_class, (0, 1000000))
    if entry_price < limits[0] or entry_price > limits[1]:
        logger.error("training_position_rejected_bad_price",
                     asset=asset, asset_class=asset_class,
                     entry_price=entry_price, limits=limits,
                     msg="Entry price outside sane range for asset class")
        return None

    # Per-strategy position limit (prevent one strategy from hogging all slots)
    MAX_PER_STRATEGY = 6
    strat_count = sum(1 for p in existing if p.strategy == strategy)
    if strat_count >= MAX_PER_STRATEGY:
        logger.warning("training_position_rejected",
                       asset=asset, reason="STRATEGY_LIMIT",
                       strategy=strategy, count=strat_count, max=MAX_PER_STRATEGY)
        return None

    # Per-strategy-per-class cap (prevent v10 from stacking 5 crypto LONGs in a down market)
    STRATEGY_CLASS_CAPS = {
        ("v10_mean_reversion", "crypto"): 2,
        ("v10_mean_reversion", "stock"): 3,
        ("v9_breakout", "crypto"): 2,
    }
    sc_cap = STRATEGY_CLASS_CAPS.get((strategy, asset_class))
    if sc_cap:
        sc_count = sum(1 for p in existing if p.strategy == strategy and p.asset_class == asset_class)
        if sc_count >= sc_cap:
            logger.warning("training_position_rejected",
                           asset=asset, reason="STRATEGY_CLASS_CAP",
                           strategy=strategy, asset_class=asset_class,
                           count=sc_count, max=sc_cap)
            return None

    # Stock trades only during US market hours (avoid $0 flat exits)
    if asset_class == "stock":
        try:
            from bahamut.data.live_data import _is_us_market_open
            if not _is_us_market_open():
                logger.info("training_position_rejected_market_closed",
                            asset=asset, strategy=strategy,
                            reason="US market closed — stock trades blocked outside hours")
                return None
        except Exception:
            pass  # If check fails, allow the trade

    # Sentiment gate — block LONGs in fear markets
    # BUT: skip for crypto if regime != CRASH. The orchestrator's
    # price-action check already confirmed the crash is over for this asset
    # (price above EMA200 + RSI > 40), even if F&G hasn't updated yet.
    if direction == "LONG" and asset_class in ("crypto", "stock"):
        skip_sentiment = (asset_class == "crypto" and regime != "CRASH")
        if not skip_sentiment:
            try:
                from bahamut.sentiment.gate import check_sentiment
                blocked, reason = check_sentiment(asset, direction, asset_class)
                if blocked:
                    logger.info("training_position_rejected_sentiment",
                                asset=asset, strategy=strategy, reason=reason)
                    return None
            except Exception:
                pass  # If sentiment check fails, allow the trade

    # CRASH SHORT safety limits
    if direction == "SHORT" and regime == "CRASH":
        # 1. Daily loss cap: max $1000 in CRASH SHORT losses per day
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text as sql_text
            with sync_engine.connect() as conn:
                row = conn.execute(sql_text("""
                    SELECT COALESCE(SUM(pnl), 0) as daily_short_pnl
                    FROM training_trades
                    WHERE direction = 'SHORT' AND regime = 'CRASH'
                      AND exit_time > NOW() - INTERVAL '24 hours'
                      AND pnl < 0
                """)).mappings().first()
                daily_loss = abs(float(row["daily_short_pnl"])) if row else 0
                if daily_loss >= 1000:
                    logger.warning("training_crash_short_daily_cap",
                                   asset=asset, daily_loss=daily_loss,
                                   reason="CRASH SHORT daily loss cap ($1000) reached")
                    return None
        except Exception:
            pass

        # 2. Max 2 concurrent CRASH SHORTs
        crash_shorts = sum(1 for p in existing if p.direction == "SHORT" and p.regime == "CRASH")
        if crash_shorts >= 2:
            logger.info("training_crash_short_concurrent_cap",
                        asset=asset, count=crash_shorts,
                        reason="Max 2 concurrent CRASH SHORTs")
            return None

    # Strategy loss-streak circuit breaker for v5_base
    try:
        if strategy == "v5_base":
            from bahamut.db.query import run_query_one
            stats = run_query_one("""
                SELECT COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses
                FROM training_trades WHERE strategy = 'v5_base'
            """)
            if stats:
                total = int(stats["trades"] or 0)
                wins = int(stats["wins"] or 0)
                losses = int(stats["losses"] or 0)
                wr = wins / max(1, wins + losses)

                # HARD BLOCK: WR < 40% with 100+ trades → disable crypto entirely
                # v5_base crypto: -$462. v5_base stock: +$1,036. Only stocks work.
                if total >= 100 and wr < 0.40 and asset_class == "crypto":
                    logger.warning("training_v5_crypto_blocked",
                                   asset=asset, wr=round(wr, 3), trades=total,
                                   reason="v5_base WR < 40% — crypto disabled, stocks only")
                    return None

                # SOFT: WR < 45% with 50+ trades → halve risk
                if total >= 50 and wr < 0.45:
                    risk_amount = round(risk_amount * 0.5, 2)
                    logger.warning("training_v5_circuit_breaker",
                                   asset=asset, wr=round(wr, 3), trades=total,
                                   risk_reduced_to=risk_amount,
                                   reason="v5_base WR < 45% — half risk")
    except Exception:
        pass

    # ── Risk engine size multiplier ──
    # Applied after strategy-specific circuit breakers, before size calculation.
    try:
        from bahamut.training.risk_engine import get_size_multiplier
        re_mult = get_size_multiplier()
        if re_mult <= 0:
            logger.info("training_risk_engine_size_block",
                        asset=asset, strategy=strategy, multiplier=re_mult,
                        reason="Risk engine size_multiplier=0 — trade blocked")
            _increment_counter(_get_redis(), "bahamut:counters:risk_engine_size_blocks")
            return None
        elif re_mult < 1.0:
            original_risk = risk_amount
            risk_amount = round(risk_amount * re_mult, 2)
            logger.info("training_risk_engine_size_reduced",
                        asset=asset, strategy=strategy,
                        multiplier=re_mult, original=original_risk,
                        reduced_to=risk_amount)
            _increment_counter(_get_redis(), "bahamut:counters:risk_engine_size_reductions")
    except Exception:
        pass

    # Calculate SL/TP prices
    if direction == "LONG":
        stop_price = entry_price * (1 - sl_pct)
        tp_price = entry_price * (1 + tp_pct)
        size = risk_amount / max(0.01, entry_price * sl_pct)
    else:
        stop_price = entry_price * (1 + sl_pct)
        tp_price = entry_price * (1 - tp_pct)
        size = risk_amount / max(0.01, entry_price * sl_pct)

    pos = TrainingPosition(
        position_id=str(uuid.uuid4())[:12],
        asset=asset,
        asset_class=asset_class,
        strategy=strategy,
        direction=direction,
        entry_price=round(entry_price, 6),
        stop_price=round(stop_price, 6),
        tp_price=round(tp_price, 6),
        size=round(size, 8),
        risk_amount=round(risk_amount, 2),
        entry_time=datetime.now(timezone.utc).isoformat(),
        max_hold_bars=max_hold_bars,
        current_price=entry_price,
        execution_type=execution_type,
        confidence_score=confidence_score,
        trigger_reason=trigger_reason,
        regime=regime,
    )

    _save_position(pos)
    _opened_this_cycle.add(dedup_key)
    _opened_this_cycle.add(asset_key)
    open_training_position._opened_this_cycle = _opened_this_cycle

    # ── Execute on exchange (Binance/Alpaca) ──
    try:
        from bahamut.execution.router import execute_open as exec_open
        exec_result = exec_open(
            asset=asset, asset_class=asset_class, direction=direction,
            size=pos.size, risk_amount=risk_amount,
        )
        pos.execution_platform = exec_result.get("platform", "internal")
        pos.exchange_order_id = exec_result.get("order_id", "")
        if exec_result.get("fill_price") and exec_result["fill_price"] > 0:
            # Use actual fill price from exchange
            old_entry = pos.entry_price
            pos.entry_price = round(exec_result["fill_price"], 6)
            # Recalculate SL/TP based on actual fill
            if direction == "LONG":
                pos.stop_price = round(pos.entry_price * (1 - sl_pct), 6)
                pos.tp_price = round(pos.entry_price * (1 + tp_pct), 6)
            else:
                pos.stop_price = round(pos.entry_price * (1 + sl_pct), 6)
                pos.tp_price = round(pos.entry_price * (1 - tp_pct), 6)
            pos.current_price = pos.entry_price
            logger.info("exchange_fill_applied",
                        asset=asset, platform=pos.execution_platform,
                        old_entry=old_entry, fill_price=pos.entry_price,
                        order_id=pos.exchange_order_id)
            # Invalidate platform cache so pages refresh
            try:
                from bahamut.execution.router import invalidate_platform_cache
                invalidate_platform_cache(pos.execution_platform)
            except Exception:
                pass
        elif exec_result.get("status") == "error":
            logger.warning("exchange_execution_failed_using_internal",
                           asset=asset, platform=exec_result.get("platform"),
                           error=exec_result.get("error", "")[:100])
        # Always re-save to persist execution_platform + exchange_order_id
        _save_position(pos)
    except Exception as e:
        logger.warning("exchange_execution_exception", asset=asset, error=str(e)[:100])

    logger.info("training_position_opened",
                asset=asset, strategy=strategy, direction=direction,
                entry=entry_price, sl=stop_price, tp=tp_price,
                execution_type=execution_type, confidence=confidence_score)

    # Telegram notification
    try:
        from bahamut.monitoring.telegram import send_training_trade_opened
        send_training_trade_opened({
            "asset": asset, "strategy": strategy, "direction": direction,
            "entry_price": entry_price, "stop_price": stop_price,
            "tp_price": tp_price, "risk_amount": risk_amount,
            "regime": regime, "execution_type": execution_type,
            "confidence_score": confidence_score,
        })
    except Exception:
        pass

    # WebSocket live update
    try:
        from bahamut.ws.admin_live import publish_event
        publish_event("position_opened", {
            "mode": "training", "asset": asset, "strategy": strategy,
            "position_id": pos.position_id, "direction": direction,
            "entry": entry_price, "risk": risk_amount,
        })
    except Exception:
        pass

    # Invalidate risk engine cache (position count changed)
    try:
        from bahamut.training.risk_engine import invalidate_risk_cache
        invalidate_risk_cache()
    except Exception:
        pass

    return pos
# ═══════════════════════════════════════════

def reset_cycle_dedup():
    """Reset the per-cycle dedup sets. Call once at cycle start."""
    update_positions_for_asset._already_closed = set()
    open_training_position._opened_this_cycle = set()


def cleanup_invalid_positions() -> list[str]:
    """Remove invalid positions at cycle start. Returns list of removed position descriptions."""
    positions = _load_positions()
    removed = []
    seen: dict[str, str] = {}  # dedup key → position_id (keep first, remove later duplicates)

    PRICE_SANITY = {
        "forex": (0.001, 300),
        "crypto": (0.0001, 200000),
        "stock": (1, 100000),
        "commodity": (0.5, 15000),
        "index": (100, 25000),
    }

    VALID_REGIMES = {
        "v5_base": {"TREND"},
        "v9_breakout": {"TREND", "BREAKOUT", "RANGE"},
        "v10_mean_reversion": {"RANGE", "CRASH"},
    }

    for pos in positions:
        remove_reason = None

        # 1. Price sanity
        limits = PRICE_SANITY.get(pos.asset_class, (0, 1000000))
        if pos.entry_price < limits[0] or pos.entry_price > limits[1]:
            remove_reason = f"bad_price: {pos.entry_price} outside {limits} for {pos.asset_class}"

        # 2. Invalid regime (if regime is set)
        if not remove_reason and pos.regime:
            allowed = VALID_REGIMES.get(pos.strategy, set())
            if allowed and pos.regime not in allowed:
                remove_reason = f"invalid_regime: {pos.strategy} in {pos.regime}"

        # 3. Duplicate — only one position per asset allowed
        dedup_key = pos.asset  # one position per asset, not per strategy
        if not remove_reason:
            if dedup_key in seen:
                remove_reason = f"duplicate_asset: {pos.asset} (keeping {seen[dedup_key]})"
            else:
                seen[dedup_key] = pos.position_id

        if remove_reason:
            _remove_position(pos.position_id)
            removed.append(f"{pos.asset} {pos.strategy} {pos.regime}: {remove_reason}")
            logger.info("training_position_cleaned",
                        asset=pos.asset, strategy=pos.strategy,
                        position_id=pos.position_id, reason=remove_reason)

    return removed


def update_positions_for_asset(asset: str, bar: dict) -> list[TrainingTrade]:
    """Update all open positions for an asset with a new bar.
    Returns list of trades that were closed this bar."""
    positions = _load_positions()
    asset_positions = [p for p in positions if p.asset == asset]
    closed_trades = []

    high = bar.get("high", 0)
    low = bar.get("low", 0)
    close = bar.get("close", 0)

    # Dedup: track position_ids already closed this cycle to prevent double-close
    _already_closed: set = getattr(update_positions_for_asset, "_already_closed", set())

    for pos in asset_positions:
        # Skip if already closed in a previous call this cycle
        if pos.position_id in _already_closed:
            continue

        pos.current_price = close
        pos.bars_held += 1

        exit_reason = None
        exit_price = close

        # Check SL
        if pos.direction == "LONG" and low <= pos.stop_price:
            exit_reason = "SL"
            exit_price = pos.stop_price
        elif pos.direction == "SHORT" and high >= pos.stop_price:
            exit_reason = "SL"
            exit_price = pos.stop_price

        # Check TP
        if not exit_reason:
            if pos.direction == "LONG" and high >= pos.tp_price:
                exit_reason = "TP"
                exit_price = pos.tp_price
            elif pos.direction == "SHORT" and low <= pos.tp_price:
                exit_reason = "TP"
                exit_price = pos.tp_price

        # Check timeout
        if not exit_reason and pos.bars_held >= pos.max_hold_bars:
            exit_reason = "TIMEOUT"
            exit_price = close

        if exit_reason:
            # Close the position
            if pos.direction == "LONG":
                pnl = (exit_price - pos.entry_price) * pos.size
            else:
                pnl = (pos.entry_price - exit_price) * pos.size

            pnl_pct = pnl / max(0.01, pos.risk_amount)

            trade = TrainingTrade(
                trade_id=str(uuid.uuid4())[:12],
                position_id=pos.position_id,
                asset=pos.asset,
                asset_class=pos.asset_class,
                strategy=pos.strategy,
                direction=pos.direction,
                entry_price=pos.entry_price,
                exit_price=round(exit_price, 6),
                stop_price=pos.stop_price,
                tp_price=pos.tp_price,
                size=pos.size,
                risk_amount=pos.risk_amount,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 4),
                entry_time=pos.entry_time,
                exit_time=datetime.now(timezone.utc).isoformat(),
                exit_reason=exit_reason,
                bars_held=pos.bars_held,
                execution_type=pos.execution_type,
                confidence_score=pos.confidence_score,
                trigger_reason=pos.trigger_reason,
                regime=pos.regime,
            )

            actually_removed = _remove_position(pos.position_id)
            if not actually_removed:
                # Another call already closed this position — skip to avoid duplicate trade
                logger.info("training_position_already_closed",
                            asset=pos.asset, position_id=pos.position_id)
                continue

            _already_closed.add(pos.position_id)
            update_positions_for_asset._already_closed = _already_closed

            # ── Execute close on exchange (Binance/Alpaca) ──
            try:
                from bahamut.execution.router import execute_close as exec_close
                exec_result = exec_close(
                    asset=pos.asset, asset_class=pos.asset_class,
                    direction=pos.direction, size=pos.size,
                    entry_price=pos.entry_price,
                )
                trade.execution_platform = exec_result.get("platform", "internal")
                trade.exchange_order_id = exec_result.get("order_id", "")
                if exec_result.get("fill_price") and exec_result["fill_price"] > 0:
                    trade.exit_price = round(exec_result["fill_price"], 6)
                    # Recalculate PnL with actual fill
                    if pos.direction == "LONG":
                        trade.pnl = round((trade.exit_price - pos.entry_price) * pos.size, 2)
                    else:
                        trade.pnl = round((pos.entry_price - trade.exit_price) * pos.size, 2)
                    trade.pnl_pct = round(trade.pnl / max(0.01, pos.risk_amount), 4)
                    logger.info("exchange_close_fill_applied",
                                asset=pos.asset, platform=trade.execution_platform,
                                fill_price=trade.exit_price, pnl=trade.pnl)
                    # Invalidate platform cache so pages refresh
                    try:
                        from bahamut.execution.router import invalidate_platform_cache
                        invalidate_platform_cache(trade.execution_platform)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("exchange_close_exception", asset=pos.asset, error=str(e)[:100])

            _persist_trade(trade)
            _record_recent(trade)
            closed_trades.append(trade)

            # Invalidate risk engine cache (position count changed)
            try:
                from bahamut.training.risk_engine import invalidate_risk_cache
                invalidate_risk_cache()
            except Exception:
                pass

            # Set per-asset + per-strategy cooldown to prevent immediate re-entry
            try:
                r = _get_redis()
                if r:
                    # Strategy-specific cooldown duration
                    COOLDOWN_BY_STRATEGY = {"v5_base": 14400}
                    cd_time = COOLDOWN_BY_STRATEGY.get(pos.strategy, 1800)
                    r.setex(f"bahamut:training:cooldown:{pos.asset}", cd_time, "1")
                    r.setex(f"bahamut:training:cooldown:{pos.asset}:{pos.strategy}", cd_time, "1")
            except Exception:
                pass

            logger.info("training_position_closed",
                        asset=pos.asset, strategy=pos.strategy,
                        pnl=trade.pnl, reason=exit_reason, bars=pos.bars_held)

            # Telegram notification
            try:
                from bahamut.monitoring.telegram import send_training_trade_closed
                send_training_trade_closed({
                    "asset": pos.asset, "strategy": pos.strategy,
                    "direction": pos.direction,
                    "entry_price": pos.entry_price, "exit_price": exit_price,
                    "pnl": trade.pnl, "exit_reason": exit_reason,
                    "bars_held": pos.bars_held, "risk_amount": pos.risk_amount,
                })
            except Exception:
                pass

            # WebSocket live update
            try:
                from bahamut.ws.admin_live import publish_event
                publish_event("position_closed", {
                    "mode": "training", "asset": pos.asset,
                    "strategy": pos.strategy, "position_id": pos.position_id,
                    "pnl": trade.pnl, "result": "WIN" if trade.pnl > 0.01 else ("FLAT" if abs(trade.pnl) < 0.01 else "LOSS"),
                    "exit_reason": exit_reason,
                })
            except Exception:
                pass
        else:
            # Update position in Redis
            _save_position(pos)

    return closed_trades


# ═══════════════════════════════════════════
# PERSISTENCE (DB + Redis)
# ═══════════════════════════════════════════

def _persist_trade(trade: TrainingTrade):
    """Persist closed trade to training_trades table + feed learning."""
    # DB — primary persistence
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO training_trades
                (trade_id, position_id, asset, asset_class, strategy, direction,
                 entry_price, exit_price, stop_price, tp_price, size, risk_amount,
                 pnl, pnl_pct, entry_time, exit_time, exit_reason, bars_held, regime,
                 execution_type, confidence_score, trigger_reason)
                VALUES (:tid, :pid, :a, :ac, :s, :d, :ep, :xp, :sp, :tp, :sz, :ra,
                        :pnl, :pp, :et, :xt, :xr, :bh, :reg,
                        :exec_type, :conf, :trig)
            """), {
                "tid": trade.trade_id, "pid": trade.position_id,
                "a": trade.asset, "ac": trade.asset_class,
                "s": trade.strategy, "d": trade.direction,
                "ep": trade.entry_price, "xp": trade.exit_price,
                "sp": trade.stop_price, "tp": trade.tp_price,
                "sz": trade.size, "ra": trade.risk_amount,
                "pnl": trade.pnl, "pp": trade.pnl_pct,
                "et": trade.entry_time, "xt": trade.exit_time,
                "xr": trade.exit_reason, "bh": trade.bars_held,
                "reg": trade.regime,
                "exec_type": trade.execution_type,
                "conf": trade.confidence_score,
                "trig": trade.trigger_reason,
            })
            conn.commit()
            logger.info("training_trade_persisted_to_db", trade_id=trade.trade_id,
                        asset=trade.asset, pnl=trade.pnl)
    except Exception as e:
        logger.error("TRAINING_TRADE_DB_PERSIST_FAILED",
                     trade_id=trade.trade_id, asset=trade.asset,
                     pnl=trade.pnl, error=str(e),
                     msg="Trade saved to Redis only — may disappear on deploy!")
        # Attempt simpler insert without newer columns
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO training_trades
                    (trade_id, position_id, asset, asset_class, strategy, direction,
                     entry_price, exit_price, stop_price, tp_price, size, risk_amount,
                     pnl, pnl_pct, entry_time, exit_time, exit_reason, bars_held, regime)
                    VALUES (:tid, :pid, :a, :ac, :s, :d, :ep, :xp, :sp, :tp, :sz, :ra,
                            :pnl, :pp, :et, :xt, :xr, :bh, :reg)
                """), {
                    "tid": trade.trade_id, "pid": trade.position_id,
                    "a": trade.asset, "ac": trade.asset_class,
                    "s": trade.strategy, "d": trade.direction,
                    "ep": trade.entry_price, "xp": trade.exit_price,
                    "sp": trade.stop_price, "tp": trade.tp_price,
                    "sz": trade.size, "ra": trade.risk_amount,
                    "pnl": trade.pnl, "pp": trade.pnl_pct,
                    "et": trade.entry_time, "xt": trade.exit_time,
                    "xr": trade.exit_reason, "bh": trade.bars_held,
                    "reg": trade.regime,
                })
                conn.commit()
                logger.info("training_trade_persisted_fallback", trade_id=trade.trade_id)
        except Exception as e2:
            logger.error("TRAINING_TRADE_DB_PERSIST_FALLBACK_ALSO_FAILED",
                         trade_id=trade.trade_id, error=str(e2))

    # Feed learning engine
    try:
        _feed_learning(trade)
    except Exception as e:
        logger.debug("training_learning_feed_failed", error=str(e))


def _record_recent(trade: TrainingTrade):
    """Keep last 100 trades in Redis for dashboard."""
    r = _get_redis()
    if r:
        try:
            r.lpush(REDIS_KEY_RECENT, json.dumps(asdict(trade)))
            r.ltrim(REDIS_KEY_RECENT, 0, 99)
        except Exception:
            pass


def _increment_counter(r, key: str):
    """Increment a Redis counter for verification diagnostics."""
    try:
        if r:
            r.incr(key)
            r.expire(key, 604800)  # 7 day TTL
    except Exception:
        pass


def _feed_research_learning(ctx):
    """Feed a debug_exploration trade into SEPARATE research trust keys.
    These keys are prefixed with 'research:' and have zero effect on production."""
    r = _get_redis()
    if not r:
        return
    try:
        from bahamut.training.learning_engine import _build_trust_keys, _load_trust_bucket, \
            TRUST_EMA_ALPHA, TRUST_DEFAULT
        import json as _json

        # Build research-prefixed keys (separate from production)
        prod_keys = _build_trust_keys(ctx)
        for prod_key in prod_keys:
            research_key = prod_key.replace("bahamut:training:trust:", "bahamut:training:research_trust:")
            try:
                raw = r.get(research_key)
                trust = _json.loads(raw) if raw else {
                    "trades": 0, "wins": 0, "losses": 0,
                    "trust_score": TRUST_DEFAULT, "recent_outcomes": [],
                    "recent_r_multiples": [],
                }
                trust["trades"] += 1
                if ctx.pnl > 0.01:
                    trust["wins"] += 1
                elif ctx.pnl < -0.01:
                    trust["losses"] += 1
                recent = trust.get("recent_outcomes", [])
                recent.append(ctx.outcome_score)
                trust["recent_outcomes"] = recent[-20:]
                r_mults = trust.get("recent_r_multiples", [])
                r_mults.append(ctx.r_multiple)
                trust["recent_r_multiples"] = r_mults[-20:]
                old_trust = trust.get("trust_score", TRUST_DEFAULT)
                target = 0.5 + ctx.outcome_score * 0.3
                trust["trust_score"] = round(old_trust * (1 - TRUST_EMA_ALPHA) + target * TRUST_EMA_ALPHA, 4)
                r.set(research_key, _json.dumps(trust), ex=604800)
            except Exception:
                pass
    except Exception:
        pass


def _feed_learning(trade: TrainingTrade):
    """Feed a closed training trade into all learning systems."""
    r = _get_redis()
    if not r:
        return

    # ── Enhanced learning: structured context + pattern-level trust ──
    try:
        from bahamut.training.learning_engine import compute_learning_context, update_trust_from_trade
        ctx = compute_learning_context(asdict(trade))

        # ══════════════════════════════════════════════════════════
        # FULL RESEARCH / PRODUCTION SEPARATION
        # debug_exploration trades have ZERO effect on:
        #   - production trust
        #   - production expectancy
        #   - production maturity
        #   - production suppressions
        #   - selector learning
        # They go to separate research trust keys instead.
        # ══════════════════════════════════════════════════════════
        if trade.execution_type == "debug_exploration":
            _feed_research_learning(ctx)
            _increment_counter(r, "bahamut:counters:research_trust_updates")
            logger.info("research_learning_fed",
                        strategy=trade.strategy, asset=trade.asset,
                        exit=trade.exit_reason, pnl=trade.pnl,
                        outcome=ctx.outcome_score, r_mult=ctx.r_multiple)
        else:
            update_trust_from_trade(ctx)
            _increment_counter(r, "bahamut:counters:production_trust_updates")
            logger.info("production_learning_fed",
                        strategy=trade.strategy, exit=trade.exit_reason,
                        pnl=trade.pnl, outcome=ctx.outcome_score,
                        quick_stop=ctx.quick_stop, r_mult=ctx.r_multiple)

            # Only production trades can trigger auto-suppression
            from bahamut.training.context_gate import evaluate_for_suppression
            evaluate_for_suppression(trade.strategy, trade.regime, trade.asset_class)
    except Exception as e:
        logger.warning("enhanced_learning_failed", error=str(e))

    # ── Legacy stats (kept for backward compat with dashboard) ──

    # 1. Per-strategy stats (dashboard + leaderboard)
    key = f"bahamut:training:strategy_stats:{trade.strategy}"
    try:
        raw = r.get(key)
        stats = json.loads(raw) if raw else {"wins": 0, "losses": 0, "total_pnl": 0, "trades": 0}
        stats["trades"] += 1
        stats["total_pnl"] = round(stats["total_pnl"] + trade.pnl, 2)
        if trade.pnl > 0.01:
            stats["wins"] += 1
        elif trade.pnl < -0.01:
            stats["losses"] += 1
        stats["win_rate"] = round(stats["wins"] / max(1, stats["wins"] + stats["losses"]), 4)
        stats["last_trade"] = trade.exit_time
        stats["last_asset"] = trade.asset
        stats["last_pnl"] = trade.pnl
        r.set(key, json.dumps(stats))
    except Exception:
        pass

    # 2. Per-asset-class stats
    ac_key = f"bahamut:training:class_stats:{trade.asset_class}"
    try:
        raw = r.get(ac_key)
        stats = json.loads(raw) if raw else {"wins": 0, "losses": 0, "total_pnl": 0, "trades": 0}
        stats["trades"] += 1
        stats["total_pnl"] = round(stats["total_pnl"] + trade.pnl, 2)
        if trade.pnl > 0.01:
            stats["wins"] += 1
        elif trade.pnl < -0.01:
            stats["losses"] += 1
        stats["win_rate"] = round(stats["wins"] / max(1, stats["wins"] + stats["losses"]), 4)
        r.set(ac_key, json.dumps(stats))
    except Exception:
        pass

    # 3. Global learning counter
    try:
        r.incr("bahamut:training:total_closed_trades")
    except Exception:
        pass


# ═══════════════════════════════════════════
# STATS / DASHBOARD QUERIES
# ═══════════════════════════════════════════

def get_recent_trades_from_redis() -> list[dict]:
    """Read recent closed trades from Redis. Used as fallback when DB has no rows."""
    r = _get_redis()
    if not r:
        return []
    try:
        raw = r.lrange(REDIS_KEY_RECENT, 0, 99)
        return [json.loads(x) for x in raw] if raw else []
    except Exception:
        return []


# Alias for backward compat
get_test_trades_from_redis = get_recent_trades_from_redis


def get_training_stats() -> dict:
    """Get training universe stats for dashboard. DB-backed with Redis cache."""
    r = _get_redis()
    positions = _load_positions()
    recent = []
    strategy_stats = {}
    class_stats = {}

    # Try Redis cache first
    if r:
        try:
            raw = r.lrange(REDIS_KEY_RECENT, 0, 19)
            recent = [json.loads(x) for x in raw]
        except Exception:
            pass

        for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
            try:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    strategy_stats[strat] = json.loads(raw)
            except Exception:
                pass

        for ac in ["crypto", "forex", "index", "commodity", "stock"]:
            try:
                raw = r.get(f"bahamut:training:class_stats:{ac}")
                if raw:
                    class_stats[ac] = json.loads(raw)
            except Exception:
                pass

    # If Redis stats are empty, rebuild from DB
    if not strategy_stats:
        strategy_stats, class_stats = _rebuild_stats_from_db()
    if not recent:
        recent = _get_recent_trades_from_db()

    total_trades = sum(s.get("trades", 0) for s in strategy_stats.values())
    total_pnl = sum(s.get("total_pnl", 0) for s in strategy_stats.values())
    total_wins = sum(s.get("wins", 0) for s in strategy_stats.values())

    return {
        "open_positions": len(positions),
        "total_closed_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(total_wins / max(1, total_trades), 4),
        "positions": [asdict(p) for p in positions[:20]],
        "recent_trades": recent,
        "strategy_stats": strategy_stats,
        "class_stats": class_stats,
        "assets_in_universe": len(set(p.asset for p in positions)),
    }


def _rebuild_stats_from_db() -> tuple[dict, dict]:
    """Rebuild strategy + class stats from training_trades DB table. Repopulates Redis."""
    strategy_stats = {}
    class_stats = {}
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT strategy, asset_class,
                       COUNT(*) as cnt,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       COALESCE(SUM(pnl), 0) as total_pnl
                FROM training_trades GROUP BY strategy, asset_class
            """)).mappings().all()

            for row in rows:
                s = row["strategy"]
                ac = row["asset_class"]
                cnt = int(row["cnt"])
                wins = int(row["wins"])
                losses = int(row["losses"])
                pnl = float(row["total_pnl"])
                decisive = wins + losses

                if s not in strategy_stats:
                    strategy_stats[s] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0, "win_rate": 0}
                ss = strategy_stats[s]
                ss["trades"] += cnt
                ss["wins"] += wins
                ss["losses"] += losses
                ss["total_pnl"] = round(ss["total_pnl"] + pnl, 2)
                ss["win_rate"] = round(ss["wins"] / max(1, ss["wins"] + ss["losses"]), 4)

                if ac not in class_stats:
                    class_stats[ac] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0, "win_rate": 0}
                cs = class_stats[ac]
                cs["trades"] += cnt
                cs["wins"] += wins
                cs["losses"] += losses
                cs["total_pnl"] = round(cs["total_pnl"] + pnl, 2)
                cs["win_rate"] = round(cs["wins"] / max(1, cs["wins"] + cs["losses"]), 4)

        # Write back to Redis for next fast read
        r = _get_redis()
        if r:
            try:
                for s, stats in strategy_stats.items():
                    r.set(f"bahamut:training:strategy_stats:{s}", json.dumps(stats))
                for ac, stats in class_stats.items():
                    r.set(f"bahamut:training:class_stats:{ac}", json.dumps(stats))
            except Exception:
                pass

        logger.info("training_stats_rebuilt_from_db",
                    strategies=len(strategy_stats), classes=len(class_stats))
    except Exception as e:
        logger.warning("training_stats_rebuild_failed", error=str(e))

    return strategy_stats, class_stats


def _get_recent_trades_from_db(limit: int = 20) -> list[dict]:
    """Get recent closed trades from DB."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT trade_id, asset, asset_class, strategy, direction,
                       entry_price, exit_price, pnl, pnl_pct,
                       exit_reason, bars_held, entry_time, exit_time
                FROM training_trades
                ORDER BY created_at DESC LIMIT :lim
            """), {"lim": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════
# EARLY EXECUTION EVALUATOR
# ═══════════════════════════════════════════

EARLY_CONFIG = {
    "min_score": 90,
    "max_early_per_cycle": 2,
    "max_early_pct": 0.20,          # Max 20% of open positions can be early
    "risk_multiplier": 0.5,          # 50% of normal risk
    "rsi_min": 25,
    "rsi_max": 75,
    "max_distance_pct": 1.0,
    "min_consistent_scans": 2,
    "blocked_regimes": {"transition", "crash"},
}


def evaluate_early_execution(
    asset: str,
    readiness_score: int,
    regime: str,
    direction: str,
    indicators: dict,
    distance_to_trigger: str,
) -> dict:
    """
    Evaluate whether an asset qualifies for early execution (before 4H close).

    Returns:
        eligible: bool
        reasons: list[str]
        confidence: float (0-100)
        risk_multiplier: float
    """
    # Load adaptive profile if available, else defaults
    cfg = dict(EARLY_CONFIG)
    try:
        from bahamut.training.adaptive_thresholds import get_current_profile
        profile = get_current_profile()
        if profile.mode != "WARMING_UP":
            cfg["min_score"] = profile.early_threshold
            cfg["max_early_per_cycle"] = profile.max_early_per_cycle
            cfg["risk_multiplier"] = profile.early_risk_multiplier
            if not profile.early_execution_enabled:
                return {
                    "eligible": False,
                    "reasons": [f"Early execution disabled (mode: {profile.mode})"],
                    "confidence": 0,
                    "risk_multiplier": 1.0,
                    "failed_conditions": [f"Early execution disabled by adaptive controller"],
                    "passed_conditions": [],
                }
    except Exception:
        pass
    reasons = []
    failed = []

    # 1. Score threshold
    if readiness_score < cfg["min_score"]:
        failed.append(f"Score {readiness_score} < {cfg['min_score']}")
    else:
        reasons.append(f"High readiness ({readiness_score})")

    # 2. Regime stability
    regime_lower = regime.lower() if regime else ""
    if regime_lower in cfg["blocked_regimes"]:
        failed.append(f"Regime '{regime}' is unstable")
    elif regime_lower in ("trend", "breakout"):
        reasons.append(f"Strong regime: {regime}")
    else:
        failed.append(f"Regime '{regime}' not strong enough for early entry")

    # 3. RSI bounds
    rsi = indicators.get("rsi_14", indicators.get("rsi", 50))
    if rsi < cfg["rsi_min"] or rsi > cfg["rsi_max"]:
        failed.append(f"RSI extreme ({rsi:.0f}), outside {cfg['rsi_min']}-{cfg['rsi_max']}")
    else:
        reasons.append(f"RSI healthy ({rsi:.0f})")

    # 4. Distance to trigger
    try:
        dist_val = float(str(distance_to_trigger).replace("%", "").split()[0])
    except (ValueError, IndexError):
        dist_val = 99.0
    if abs(dist_val) > cfg["max_distance_pct"]:
        failed.append(f"Distance {abs(dist_val):.1f}% > max {cfg['max_distance_pct']}%")
    else:
        reasons.append(f"Very close to trigger ({abs(dist_val):.1f}%)")

    # 5. EMA alignment
    ema_align = indicators.get("ema_alignment", "")
    if direction == "LONG" and "bullish" in str(ema_align).lower():
        reasons.append("EMA alignment confirms direction")
    elif direction == "SHORT" and "bearish" in str(ema_align).lower():
        reasons.append("EMA alignment confirms direction")
    else:
        failed.append(f"EMA alignment weak ({ema_align})")

    # 6. Portfolio early trade cap
    positions = _load_positions()
    early_count = sum(1 for p in positions if p.execution_type == "early")
    total_count = len(positions)
    max_early = max(1, int(total_count * cfg["max_early_pct"])) if total_count > 0 else cfg["max_early_per_cycle"]
    if early_count >= max_early:
        failed.append(f"Early trade cap reached ({early_count}/{max_early})")

    # 7. No existing position for this asset
    if any(p.asset == asset for p in positions):
        failed.append(f"Already holding {asset}")

    # 8. Signal consistency (check Redis for last scan direction)
    consistent = _check_scan_consistency(asset, direction)
    if not consistent:
        failed.append("Direction not consistent across last 2 scans")
    else:
        reasons.append("Direction consistent across scans")

    eligible = len(failed) == 0
    confidence = readiness_score if eligible else 0

    return {
        "eligible": eligible,
        "reasons": reasons if eligible else failed,
        "confidence": confidence,
        "risk_multiplier": cfg["risk_multiplier"] if eligible else 1.0,
        "failed_conditions": failed,
        "passed_conditions": reasons,
    }


def _check_scan_consistency(asset: str, direction: str) -> bool:
    """Check if the same direction was seen in the last 2 scans."""
    r = _get_redis()
    if not r:
        return False
    try:
        key = f"bahamut:training:scan_direction:{asset}"
        history = r.lrange(key, 0, 1)
        if len(history) < 2:
            return False
        return all(d.decode() == direction for d in history)
    except Exception:
        return False


def record_scan_direction(asset: str, direction: str):
    """Record the direction seen in this scan for consistency checking."""
    r = _get_redis()
    if not r:
        return
    try:
        key = f"bahamut:training:scan_direction:{asset}"
        r.lpush(key, direction)
        r.ltrim(key, 0, 4)  # Keep last 5
        r.expire(key, 7200)  # 2h TTL
    except Exception:
        pass
