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


def _remove_position(position_id: str):
    """Remove a closed position from Redis + mark CLOSED in DB."""
    # Redis
    r = _get_redis()
    if r:
        try:
            r.hdel(REDIS_KEY_POSITIONS, position_id)
        except Exception:
            pass

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

    # Check position limit
    current_count = get_open_position_count()
    if current_count >= TRAINING_MAX_POSITIONS:
        logger.warning("training_position_rejected",
                       asset=asset, reason="POSITION_LIMIT",
                       current=current_count, max=TRAINING_MAX_POSITIONS)
        return None

    # Check no duplicate (same asset + strategy + direction)
    existing = _load_positions()
    for p in existing:
        if p.asset == asset and p.strategy == strategy and p.direction == direction:
            logger.warning("training_position_rejected",
                           asset=asset, reason="DUPLICATE",
                           strategy=strategy, direction=direction)
            return None

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
    )

    _save_position(pos)
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

    return pos


# ═══════════════════════════════════════════
# UPDATE POSITIONS WITH NEW BAR
# ═══════════════════════════════════════════

def update_positions_for_asset(asset: str, bar: dict) -> list[TrainingTrade]:
    """Update all open positions for an asset with a new bar.
    Returns list of trades that were closed this bar."""
    positions = _load_positions()
    asset_positions = [p for p in positions if p.asset == asset]
    closed_trades = []

    high = bar.get("high", 0)
    low = bar.get("low", 0)
    close = bar.get("close", 0)

    for pos in asset_positions:
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
            )

            _remove_position(pos.position_id)
            _persist_trade(trade)
            _record_recent(trade)
            closed_trades.append(trade)

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


def _feed_learning(trade: TrainingTrade):
    """Feed a closed training trade into all learning systems."""
    r = _get_redis()
    if not r:
        return

    # 1. Per-strategy stats (dashboard + leaderboard)
    key = f"bahamut:training:strategy_stats:{trade.strategy}"
    try:
        raw = r.get(key)
        stats = json.loads(raw) if raw else {"wins": 0, "losses": 0, "total_pnl": 0, "trades": 0}
        stats["trades"] += 1
        stats["total_pnl"] = round(stats["total_pnl"] + trade.pnl, 2)
        if trade.pnl > 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1
        stats["win_rate"] = round(stats["wins"] / max(1, stats["trades"]), 4)
        stats["last_trade"] = trade.exit_time
        stats["last_asset"] = trade.asset
        stats["last_pnl"] = trade.pnl
        r.set(key, json.dumps(stats))
    except Exception:
        pass

    # 2. Per-asset-class stats (dashboard + learning)
    ac_key = f"bahamut:training:class_stats:{trade.asset_class}"
    try:
        raw = r.get(ac_key)
        stats = json.loads(raw) if raw else {"wins": 0, "losses": 0, "total_pnl": 0, "trades": 0}
        stats["trades"] += 1
        stats["total_pnl"] = round(stats["total_pnl"] + trade.pnl, 2)
        if trade.pnl > 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1
        stats["win_rate"] = round(stats["wins"] / max(1, stats["trades"]), 4)
        r.set(ac_key, json.dumps(stats))
    except Exception:
        pass

    # 3. Strategy trust score (computed from rolling window)
    trust_key = f"bahamut:training:trust:{trade.strategy}"
    try:
        raw = r.get(trust_key)
        trust = json.loads(raw) if raw else {
            "trades": 0, "wins": 0, "recent_pnls": [],
            "trust_score": 0.5, "provisional": True,
        }
        trust["trades"] += 1
        if trade.pnl > 0:
            trust["wins"] += 1

        # Keep last 20 PnLs for rolling metrics
        recent = trust.get("recent_pnls", [])
        recent.append(round(trade.pnl, 2))
        if len(recent) > 20:
            recent = recent[-20:]
        trust["recent_pnls"] = recent

        # Compute trust score (requires MIN_SAMPLES)
        from bahamut.intelligence.learning_progress import MIN_SAMPLES_FOR_TRUST
        if trust["trades"] >= MIN_SAMPLES_FOR_TRUST:
            wr = trust["wins"] / max(1, trust["trades"])
            recent_wr = sum(1 for p in recent if p > 0) / max(1, len(recent))
            trust["trust_score"] = round(0.6 * wr + 0.4 * recent_wr, 4)
            trust["provisional"] = False
        else:
            trust["trust_score"] = 0.5
            trust["provisional"] = True

        trust["last_updated"] = trade.exit_time
        r.set(trust_key, json.dumps(trust))
    except Exception:
        pass

    # 4. Global learning counter (for progress tracking)
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

        for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
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
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       COALESCE(SUM(pnl), 0) as total_pnl
                FROM training_trades GROUP BY strategy, asset_class
            """)).mappings().all()

            for row in rows:
                s = row["strategy"]
                ac = row["asset_class"]
                cnt = int(row["cnt"])
                wins = int(row["wins"])
                pnl = float(row["total_pnl"])

                if s not in strategy_stats:
                    strategy_stats[s] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0, "win_rate": 0}
                ss = strategy_stats[s]
                ss["trades"] += cnt
                ss["wins"] += wins
                ss["losses"] += cnt - wins
                ss["total_pnl"] = round(ss["total_pnl"] + pnl, 2)
                ss["win_rate"] = round(ss["wins"] / max(1, ss["trades"]), 4)

                if ac not in class_stats:
                    class_stats[ac] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0, "win_rate": 0}
                cs = class_stats[ac]
                cs["trades"] += cnt
                cs["wins"] += wins
                cs["losses"] += cnt - wins
                cs["total_pnl"] = round(cs["total_pnl"] + pnl, 2)
                cs["win_rate"] = round(cs["wins"] / max(1, cs["trades"]), 4)

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
