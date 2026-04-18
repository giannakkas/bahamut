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
# Schema assertions — Alembic is the sole source of truth.
# Runtime DDL removed. These columns must exist via migration.
# ═══════════════════════════════════════════
_SCHEMA_VERIFIED = False


def _ensure_substrategy_column() -> bool:
    """Verify that substrategy and data_mode columns exist.
    Does NOT create them — that's Alembic's job.
    Returns True if columns exist, False with ERROR log if not."""
    global _SCHEMA_VERIFIED
    if _SCHEMA_VERIFIED:
        return True
    try:
        from bahamut.db.schema.assertions import assert_column_exists
        ok = all([
            assert_column_exists("training_positions", "substrategy"),
            assert_column_exists("training_positions", "data_mode"),
            assert_column_exists("training_trades", "substrategy"),
            assert_column_exists("training_trades", "data_mode"),
        ])
        if ok:
            _SCHEMA_VERIFIED = True
        return ok
    except Exception as e:
        logger.warning("schema_assertion_check_failed", error=str(e)[:200])
        return True  # Assume present to avoid blocking trades on assertion error


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

    # ── Phase 2 Item 4: canonical execution state (broker truth) ──
    # These are populated from ExecutionResult at open time. They exist even
    # for legacy positions (as empty/zero defaults) so every consumer can
    # rely on key presence.
    client_order_id: str = ""
    order_lifecycle: str = ""             # PENDING/SUBMITTED/ACCEPTED/FILLED/PARTIAL/REJECTED/ERROR/INTERNAL
    fill_status: str = ""                 # UNFILLED/PARTIAL/FILLED
    submitted_qty: float = 0.0
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    avg_fill_price: float = 0.0           # Broker-confirmed (may differ from entry_price pre-fill)
    submitted_at: str = ""
    accepted_at: str = ""
    filled_at: str = ""
    reference_price: float = 0.0          # Price at submission — used for slippage calc
    commission: float = 0.0
    commission_asset: str = ""
    slippage_abs: float = 0.0
    slippage_pct: float = 0.0

    # ── Phase 3 Item 7: sub-strategy tag (v10_range_long / v10_range_short
    # / v10_crash_short / empty for non-v10). Enables independent trust,
    # expectancy, suppression, cooldowns, diagnostics per sub-path.
    substrategy: str = ""

    # ── Phase 4 Item 12: data origin tag at position creation time.
    # 'live' / 'stale_cache' / 'synthetic_dev'. Used by _save_position
    # invariant to refuse any non-live position when BLOCK_SYNTHETIC is on.
    # Defaults to 'live' for legacy positions and code paths that don't
    # propagate the mode (so we never reject something we couldn't classify).
    data_mode: str = "live"

    # ── Broker-side bracket orders (SL/TP placed on exchange after fill)
    bracket_sl_order_id: str = ""
    bracket_tp_order_id: str = ""

    # ── Funding rate accrual for perpetual futures (USD, positive = cost)
    funding_accrued: float = 0.0

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
    pnl_pct: float          # R-multiple: pnl / risk_amount (how many R's)
    entry_time: str
    exit_time: str
    exit_reason: str     # SL / TP / TIMEOUT / MANUAL
    bars_held: int
    return_pct: float = 0.0  # Actual percentage return: pnl / (entry_price * size)
    regime: str = ""
    execution_type: str = "standard"
    confidence_score: float = 0.0
    trigger_reason: str = "4h_close"
    exchange_order_id: str = ""           # Binance/Alpaca order ID
    execution_platform: str = "internal"  # "binance" | "alpaca" | "internal"

    # ── Phase 2 Item 4: execution costs for net-vs-gross PnL (Phase 5 prep) ──
    entry_commission: float = 0.0
    exit_commission: float = 0.0
    entry_slippage_abs: float = 0.0
    exit_slippage_abs: float = 0.0
    entry_lifecycle: str = ""             # lifecycle at entry
    exit_lifecycle: str = ""              # lifecycle at exit

    # ── Phase 3 Item 7: sub-strategy tag propagated from Position ──
    substrategy: str = ""

    # ── Phase 4 Item 12: data origin at trade time ──
    data_mode: str = "live"


# ═══════════════════════════════════════════
# POSITION MANAGEMENT (DB-backed + Redis cache)
# DB is the canonical source. Redis is a fast cache.
# On load: try Redis first (fast), reconcile from DB if mismatch.
# On write: always write to BOTH.
# ═══════════════════════════════════════════

def _load_positions() -> list[TrainingPosition]:
    """Load all open training positions. Redis first, DB fallback.
    Phase 2 Item 5: filters out crypto positions that violate the
    broker-only invariant — consistent with _save_position and
    _load_positions_from_db. No invariant-violating crypto row can
    surface to any caller via this function."""
    # Try Redis (fast path)
    r = _get_redis()
    if r:
        try:
            raw = r.hgetall(REDIS_KEY_POSITIONS)
            if raw:
                positions = []
                skipped = 0
                for v in raw.values():
                    d = json.loads(v)
                    try:
                        pos = TrainingPosition(**d)
                    except TypeError:
                        # Drop fields unknown to the current dataclass (schema drift safety)
                        known = {k: v_ for k, v_ in d.items()
                                 if k in TrainingPosition.__dataclass_fields__}
                        pos = TrainingPosition(**known)
                    # Invariant check — same as _save_position
                    if (pos.asset_class == "crypto"
                            and (pos.execution_platform == "internal"
                                 or not pos.exchange_order_id)):
                        skipped += 1
                        # Remove from Redis to prevent re-surface
                        try:
                            r.hdel(REDIS_KEY_POSITIONS, pos.position_id)
                        except Exception:
                            pass
                        continue
                    positions.append(pos)
                if skipped > 0:
                    logger.warning("training_load_positions_filtered_invariant_violations",
                                   skipped=skipped, source="redis")
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

        # Ensure new columns exist (idempotent, fast no-op after first call)
        _ensure_substrategy_column()

        # Try full query first; if columns don't exist yet, fall back to
        # legacy query on a FRESH connection (SQLAlchemy 2.x poisons the
        # connection after a failed execute — rollback doesn't help).
        rows = None
        try:
            with sync_engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT position_id, asset, asset_class, strategy, direction,
                           entry_price, stop_price, tp_price, size, risk_amount,
                           entry_time, bars_held, max_hold_bars, current_price,
                           execution_type, confidence_score, trigger_reason,
                           execution_platform, exchange_order_id,
                           COALESCE(substrategy, '') as substrategy,
                           COALESCE(data_mode, 'live') as data_mode
                    FROM training_positions WHERE status = 'OPEN'
                """)).mappings().all()
        except Exception as _sel_err:
            logger.warning("training_load_positions_full_select_failed",
                           reason=str(_sel_err)[:200])
            rows = None

        if rows is None:
            # Fallback: legacy columns only, fresh connection
            try:
                with sync_engine.connect() as conn2:
                    rows = conn2.execute(text("""
                        SELECT position_id, asset, asset_class, strategy, direction,
                               entry_price, stop_price, tp_price, size, risk_amount,
                               entry_time, bars_held, max_hold_bars, current_price,
                               execution_type, confidence_score, trigger_reason
                        FROM training_positions WHERE status = 'OPEN'
                    """)).mappings().all()
            except Exception as _sel_err2:
                logger.error("training_load_positions_legacy_select_failed",
                             reason=str(_sel_err2)[:200])
                return []

        positions = []
        skipped_invariant_violations = []
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
                execution_platform=str(row.get("execution_platform") or "internal"),
                exchange_order_id=str(row.get("exchange_order_id") or ""),
                substrategy=str(row.get("substrategy") or ""),
                data_mode=str(row.get("data_mode") or "live"),
            )

            # Invariant enforcement on DB reload
            if (pos.asset_class == "crypto"
                    and (pos.execution_platform == "internal"
                         or not pos.exchange_order_id)):
                skipped_invariant_violations.append({
                    "position_id": pos.position_id,
                    "asset": pos.asset,
                    "platform": pos.execution_platform,
                    "has_order_id": bool(pos.exchange_order_id),
                })
                continue
            positions.append(pos)

        # Close violations in DB (fresh connection)
        if skipped_invariant_violations:
            try:
                with sync_engine.connect() as upd_conn:
                    for viol in skipped_invariant_violations:
                        upd_conn.execute(
                            text("UPDATE training_positions SET status = 'CLOSED' "
                                 "WHERE position_id = :pid AND status = 'OPEN'"),
                            {"pid": viol["position_id"]},
                        )
                    upd_conn.commit()
            except Exception:
                pass
            logger.error("training_positions_load_invariant_violations",
                         count=len(skipped_invariant_violations),
                         rows=skipped_invariant_violations[:5])
            r = _get_redis()
            if r:
                try:
                    import json as _jinv
                    r.set("bahamut:crypto_mirror_load_violations_last",
                          _jinv.dumps(skipped_invariant_violations), ex=86400)
                except Exception:
                    pass

        # Repopulate Redis cache from DB
        if positions:
            r = _get_redis()
            if r:
                try:
                    r.delete(REDIS_KEY_POSITIONS)
                except Exception:
                    pass
            for pos in positions:
                try:
                    _save_position(pos)
                except Exception:
                    pass

        logger.info("training_positions_loaded_from_db", count=len(positions))
        return positions
    except Exception as e:
        logger.error("training_load_positions_db_failed", error=str(e))
        return []


def cleanup_crypto_internal_positions() -> dict:
    """Force-close any crypto positions that violate the broker-only invariant.
    Runs periodically to clean up legacy violations.

    Phase 2 Item 5 additions:
      - Also closes DB rows where status='OPEN' and
        (execution_platform='internal' OR exchange_order_id='') for crypto.
        This catches rows that never reach _load_positions (e.g. a position
        persisted pre-invariant and never touched since).
      - Returns both Redis-side and DB-side cleanup counts.
    Returns stats: {closed: [...], db_closed: N, total: N}"""
    closed = []
    db_closed = 0
    try:
        positions = _load_positions()
        for p in positions:
            if p.asset_class == "crypto" and (p.execution_platform == "internal" or not p.exchange_order_id):
                try:
                    _remove_position(p.position_id)
                    closed.append({"asset": p.asset, "position_id": p.position_id,
                                   "strategy": p.strategy, "direction": p.direction})
                    logger.warning("crypto_internal_position_cleaned",
                                   asset=p.asset, position_id=p.position_id,
                                   reason="invariant_violation_cleanup")
                except Exception as e:
                    logger.error("crypto_internal_cleanup_failed",
                                 asset=p.asset, error=str(e)[:100])

        # DB-side cleanup: catch any crypto OPEN rows that slipped past the
        # Redis layer (e.g. legacy rows from before the invariant).
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            # List of crypto asset class tags — match what _save_position checks
            with sync_engine.connect() as conn:
                result = conn.execute(text("""
                    UPDATE training_positions
                    SET status = 'CLOSED'
                    WHERE status = 'OPEN'
                      AND asset_class = 'crypto'
                      AND (execution_platform = 'internal' OR execution_platform IS NULL
                           OR exchange_order_id = '' OR exchange_order_id IS NULL)
                """))
                db_closed = result.rowcount if result.rowcount is not None else 0
                conn.commit()
                if db_closed > 0:
                    logger.warning("crypto_internal_db_cleanup",
                                   db_rows_closed=db_closed,
                                   reason="legacy_invariant_violations")
        except Exception as e:
            logger.error("crypto_internal_db_cleanup_failed", error=str(e)[:150])

        # Track in Redis
        r = _get_redis()
        if r and (closed or db_closed > 0):
            try:
                import json as _j
                r.set("bahamut:crypto_mirror_cleanup_last",
                      _j.dumps({"redis_closed": closed, "db_closed": db_closed,
                                "total": len(closed) + db_closed}),
                      ex=86400)
            except Exception:
                pass
    except Exception as e:
        logger.error("cleanup_crypto_internal_positions_exception", error=str(e)[:200])
    return {"closed": closed, "db_closed": db_closed, "total": len(closed) + db_closed}


def _save_position(pos: TrainingPosition):
    """Save a position to Redis + DB (dual write).
    HARD INVARIANT: crypto positions MUST have broker-confirmed execution.
    Rejects crypto positions where:
      - execution_platform == 'internal' (should be binance_futures), OR
      - exchange_order_id is empty, OR
      - order_lifecycle (if set) is not in FILLED/PARTIAL/ACCEPTED.
    Internal simulation for crypto is never allowed at the persistence layer."""
    # ── HARD INVARIANT: crypto must be broker-backed ──
    if pos.asset_class == "crypto":
        missing_order_id = not pos.exchange_order_id
        internal_platform = pos.execution_platform == "internal"
        # Phase 2 Item 4: also reject if lifecycle is set but indicates failure
        bad_lifecycle = (
            pos.order_lifecycle not in ("", "FILLED", "PARTIAL", "ACCEPTED", "SUBMITTED")
            if pos.order_lifecycle else False
        )
        if missing_order_id or internal_platform or bad_lifecycle:
            r = _get_redis()
            try:
                _increment_counter(r, "bahamut:counters:crypto_mirror_aborts")
                if r:
                    r.sadd("bahamut:crypto_mirror_abort_last_assets", pos.asset)
                    r.expire("bahamut:crypto_mirror_abort_last_assets", 86400)
            except Exception:
                pass
            logger.error("save_position_aborted_crypto_internal_invariant",
                         asset=pos.asset, strategy=pos.strategy,
                         platform=pos.execution_platform,
                         order_id=pos.exchange_order_id,
                         lifecycle=pos.order_lifecycle,
                         fill_status=pos.fill_status,
                         reason="Crypto must have broker execution with valid lifecycle; internal/failed not allowed")
            return  # Do NOT persist — invariant violation

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
        # Phase 3 Item 7: ensure substrategy column exists (idempotent)
        _ensure_substrategy_column()
        with sync_engine.connect() as conn:
            try:
                conn.execute(text("""
                    INSERT INTO training_positions
                    (position_id, asset, asset_class, strategy, direction,
                     entry_price, stop_price, tp_price, size, risk_amount,
                     entry_time, bars_held, max_hold_bars, current_price,
                     execution_type, confidence_score, trigger_reason, status,
                     substrategy, data_mode)
                    VALUES (:pid, :a, :ac, :s, :d, :ep, :sp, :tp, :sz, :ra,
                            :et, :bh, :mhb, :cp, :ext, :cs, :tr, 'OPEN', :sub, :dm)
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
                    "sub": pos.substrategy or "",
                    "dm": pos.data_mode or "live",
                })
            except Exception as _insert_err:
                # Column missing or unknown — fall back to legacy INSERT
                # without substrategy so production never hard-fails.
                conn.rollback()
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
                logger.debug("training_position_insert_fallback_no_substrategy",
                             reason=str(_insert_err)[:100])
            conn.commit()
    except Exception as e:
        logger.error("training_save_position_db_failed",
                     position_id=pos.position_id, error=str(e))


def _remove_position(position_id: str) -> bool:
    """Remove a closed position from Redis + mark CLOSED in DB.
    Returns True if position was actually removed (first caller wins).
    Returns False if already removed (duplicate close attempt)."""
    removed_from_redis = False

    # Redis: hdel returns count of keys removed — 0 means already gone
    r = _get_redis()
    if r:
        try:
            count = r.hdel(REDIS_KEY_POSITIONS, position_id)
            removed_from_redis = count > 0
        except Exception:
            pass

    # DB: ALWAYS mark as CLOSED — even if Redis didn't have it.
    # Without this, Railway redeploys that clear Redis leave ghost OPEN rows
    # in DB, which get reloaded as duplicates on next DB reconciliation.
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            result = conn.execute(text(
                "UPDATE training_positions SET status = 'CLOSED' WHERE position_id = :pid AND status = 'OPEN'"
            ), {"pid": position_id})
            conn.commit()
            if result.rowcount > 0:
                return True  # DB had it as OPEN → we closed it
    except Exception as e:
        logger.error("training_remove_position_db_failed",
                     position_id=position_id, error=str(e))

    return removed_from_redis


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
    substrategy: str = "",
    data_mode: str = "live",
    signal_id: str = "",
) -> TrainingPosition | None:
    """Open a new training position. Returns the position or None if rejected."""
    from bahamut.config_assets import TRAINING_MAX_POSITIONS

    # ═══════════════════════════════════════════
    # PRODUCTION: Idempotency guard via OrderManager
    # Prevents duplicate orders from retries, overlapping cycles,
    # or multi-worker race conditions. signal_id is UNIQUE in DB.
    # ═══════════════════════════════════════════
    if not signal_id:
        # Generate a deterministic signal_id from the trade params
        # so the same signal in the same cycle produces the same ID.
        import hashlib
        sig_data = f"{asset}:{strategy}:{direction}:{entry_price:.2f}:{trigger_reason}"
        signal_id = hashlib.sha256(sig_data.encode()).hexdigest()[:24]

    # ═══════════════════════════════════════════
    # PRODUCTION: Cross-worker execution lock
    # Prevents two workers from opening the same trade simultaneously.
    # Lock is keyed on signal_id and has 60s TTL as safety net.
    # DB UNIQUE on signal_id in order_intents is the backup.
    # ═══════════════════════════════════════════
    _lock_held_signal = None
    try:
        from bahamut.execution.order_manager import OrderManager as _OMLock
        if not _OMLock().acquire_execution_lock(signal_id, ttl=60):
            logger.info("training_position_rejected_exec_lock",
                        asset=asset, strategy=strategy, signal_id=signal_id)
            try:
                from bahamut.training.rejection_tracker import record_rejection
                record_rejection(asset=asset, strategy=strategy, direction=direction,
                                 signal_id=signal_id, reason_code="exec_lock_held",
                                 reason_detail="another worker holds signal lock")
            except Exception:
                pass
            return None
        _lock_held_signal = signal_id
    except Exception as _lock_err:
        logger.debug("exec_lock_acquire_failed_nonfatal", error=str(_lock_err)[:100])
        # Proceed — DB UNIQUE on signal_id still prevents duplicates


    try:
        _order_intent_id = None
        try:
            from bahamut.execution.order_manager import OrderManager
            mgr = OrderManager()
            intent = mgr.create_intent(
                asset=asset, asset_class=asset_class,
                direction=direction, strategy=strategy,
                size=risk_amount / max(0.01, entry_price * sl_pct) if sl_pct > 0 else 0,
                signal_id=signal_id,
                risk_amount=risk_amount,
                sl_pct=sl_pct, tp_pct=tp_pct,
                substrategy=substrategy,
                intended_price=entry_price,
            )
            if intent is None:
                # Duplicate signal — already processed
                logger.info("training_position_duplicate_blocked",
                            asset=asset, strategy=strategy,
                            signal_id=signal_id)
                return None
            _order_intent_id = intent["intent_id"]
        except Exception as _idmp_err:
            # OrderManager not available — continue without idempotency
            # (safe for paper trading, should be fixed for production)
            logger.debug("order_manager_unavailable",
                         error=str(_idmp_err)[:100])

        # ═══════════════════════════════════════════
        # Phase 4 Item 12: SYNTHETIC DATA HARD BLOCK
        # Reject any position computed from synthetic_dev candles when
        # BAHAMUT_BLOCK_SYNTHETIC=1 (production default). This prevents
        # learning trust/expectancy on np.random outcomes.
        # ═══════════════════════════════════════════
        try:
            from bahamut.data.live_data import BLOCK_SYNTHETIC
            if BLOCK_SYNTHETIC and data_mode == "synthetic_dev":
                logger.error("training_position_synthetic_blocked",
                             asset=asset, strategy=strategy, direction=direction,
                             data_mode=data_mode,
                             reason="BAHAMUT_BLOCK_SYNTHETIC=1 prevents synthetic trades")
                _increment_counter(_get_redis(),
                                   "bahamut:counters:synthetic_position_blocks")
                return None
        except Exception:
            pass

        _original_risk_amount = risk_amount  # Preserve for composite floor check

        # ── Volatility-targeted sizing ──
        # Scale risk by inverse realized vol: high-vol assets get smaller positions,
        # low-vol assets get larger. Target = 30% annualized vol.
        try:
            from bahamut.features.indicators import get_realized_vol
            rv = get_realized_vol(asset, lookback_days=30)
            if rv > 0:
                _VOL_TARGET = 0.30
                vol_scalar = min(1.5, max(0.3, _VOL_TARGET / rv))
                if abs(vol_scalar - 1.0) > 0.05:  # only apply if material
                    risk_amount = round(risk_amount * vol_scalar, 2)
                    _original_risk_amount = risk_amount  # update floor reference
                    logger.info("vol_targeted_sizing",
                                asset=asset, realized_vol=round(rv, 3),
                                target=_VOL_TARGET, scalar=round(vol_scalar, 2),
                                scaled_risk=round(risk_amount, 2))
        except Exception:
            pass

        # ═══════════════════════════════════════════
        # ENGINE-LEVEL SUPPRESS MAP — catches ALL signal paths
        # Single choke point every trade must pass through. Strategy.evaluate(),
        # debug_exploration, and CRASH SHORT all converge here.
        # Canonical sources: config_assets.TRAINING_SUPPRESS +
        # Phase 3 Item 7: config_assets.SUBSTRATEGY_SUPPRESS (per substrategy).
        # ═══════════════════════════════════════════
        from bahamut.config_assets import TRAINING_SUPPRESS, SUBSTRATEGY_SUPPRESS
        global_block = TRAINING_SUPPRESS.get("*", set())
        strat_block = TRAINING_SUPPRESS.get(strategy, set())
        if asset in global_block or asset in strat_block:
            logger.info("training_engine_suppressed",
                        asset=asset, strategy=strategy, direction=direction,
                        reason="ENGINE_SUPPRESS_MAP")
            _increment_counter(_get_redis(), "bahamut:counters:engine_suppress_blocks")
            return None
        # Phase 3 Item 7 — substrategy block
        if substrategy and asset in SUBSTRATEGY_SUPPRESS.get(substrategy, set()):
            logger.info("training_engine_substrategy_suppressed",
                        asset=asset, strategy=strategy, substrategy=substrategy,
                        direction=direction, reason="SUBSTRATEGY_SUPPRESS_MAP")
            _increment_counter(_get_redis(), "bahamut:counters:substrategy_suppress_blocks")
            return None

        # ── Crash-short specific suppress ──
        if execution_type == "crash_short":
            from bahamut.config_assets import CRASH_SHORT_SUPPRESS, CRASH_SHORT_PENALIZE
            if asset in CRASH_SHORT_SUPPRESS:
                logger.info("training_engine_suppressed",
                            asset=asset, strategy=strategy, direction=direction,
                            reason="CRASH_SHORT_SUPPRESS_MAP")
                _increment_counter(_get_redis(), "bahamut:counters:crash_short_suppress_blocks")
                return None
            # Crash-short penalty: halve risk for borderline assets
            if asset in CRASH_SHORT_PENALIZE:
                risk_amount = round(risk_amount * 0.5, 2)
                logger.info("crash_short_penalty_applied",
                            asset=asset, original_risk=risk_amount * 2,
                            reduced_to=risk_amount, reason="CRASH_SHORT_PENALIZE_MAP")

        # Check position limit (with Redis lock for multi-worker safety)
        _cap_lock_acquired = False
        try:
            r = _get_redis()
            if r:
                _cap_lock_acquired = bool(r.set(
                    "bahamut:lock:position_cap_check", "1", nx=True, ex=10
                ))
        except Exception:
            pass

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

        # Per-strategy drawdown block (from risk_engine per-strategy DD tracker)
        try:
            import redis as _redis_strat, os as _os_strat
            _rr_strat = _redis_strat.from_url(
                _os_strat.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                socket_connect_timeout=1)
            _strat_dd_raw = _rr_strat.get(f"bahamut:strategy_dd:{strategy}")
            if _strat_dd_raw:
                _strat_dd = float(_strat_dd_raw)
                if _strat_dd >= 15.0:
                    logger.info("training_position_rejected_strategy_dd",
                                asset=asset, strategy=strategy, dd_pct=_strat_dd)
                    _increment_counter(_get_redis(), "bahamut:counters:strategy_dd_blocks")
                    try:
                        from bahamut.training.rejection_tracker import record_rejection
                        record_rejection(asset=asset, strategy=strategy, direction=direction,
                                         signal_id=signal_id, reason_code="strategy_dd_block",
                                         reason_detail=f"{strategy} dd_pct={_strat_dd:.1f}%")
                    except Exception:
                        pass
                    return None
        except Exception:
            pass

        # ── Adaptive news risk size multiplier ──
        # CAUTION=0.75, RESTRICTED=0.5, FROZEN would have been blocked in selector
        try:
            from bahamut.intelligence.adaptive_news_risk import (
                ADAPTIVE_NEWS_ENABLED, get_asset_news_state, MODES,
            )
            if ADAPTIVE_NEWS_ENABLED:
                news_state = get_asset_news_state(asset)
                news_mult = MODES.get(news_state.mode, {}).get("size_mult", 1.0)
                if news_mult < 1.0 and news_mult > 0:
                    original_risk = risk_amount
                    risk_amount = round(risk_amount * news_mult, 2)
                    logger.info("training_news_size_reduced",
                                asset=asset, strategy=strategy,
                                news_mode=news_state.mode, multiplier=news_mult,
                                original=original_risk, reduced_to=risk_amount)
                    _increment_counter(_get_redis(), "bahamut:counters:news_size_reductions")
                    _increment_counter(_get_redis(), "bahamut:counters:adaptive_news_size_reductions")
        except Exception:
            pass

        # ── AI Decision Service sizing (per-candidate + global) ──
        # Uses clamped values from ai_decision_service (Opus or rule-based fallback)
        try:
            from bahamut.intelligence.ai_decision_service import get_ai_decision
            ai_dec = get_ai_decision(
                asset=asset, asset_class=asset_class,
                strategy=strategy, direction=direction,
            )
            ad = ai_dec.get("asset_decision", {})
            ga = ai_dec.get("global_adjustments", {})

            # Per-candidate size multiplier (clamped 0.25-1.0)
            candidate_mult = ad.get("size_multiplier", 1.0)
            # Global posture multiplier (clamped 0.25-1.0)
            global_mult = ga.get("size_multiplier", 1.0)
            # Combined (both already clamped by decision service)
            combined_mult = round(candidate_mult * global_mult, 3)

            if combined_mult < 1.0 and combined_mult > 0:
                original_risk = risk_amount
                risk_amount = round(risk_amount * combined_mult, 2)
                logger.info("execution_ai_sizing_applied",
                            asset=asset, strategy=strategy,
                            posture=ai_dec.get("posture", "unknown"),
                            candidate_mult=candidate_mult,
                            global_mult=global_mult,
                            combined_mult=combined_mult,
                            original=original_risk,
                            reduced_to=risk_amount,
                            source=ai_dec.get("_source", "unknown"))
        except Exception:
            pass

        # Floor guard: skip trades where composite sizing shrinks below viability
        # Typical taker fee is 0.04% → round-trip 0.08%. A trade risking less than
        # 10% of originally requested risk is not worth opening.
        _MIN_RISK_FRACTION = 0.10
        if _original_risk_amount > 0 and risk_amount / _original_risk_amount < _MIN_RISK_FRACTION:
            logger.info("training_position_rejected_composite_floor",
                        asset=asset, strategy=strategy,
                        final_risk=round(risk_amount, 2),
                        original_risk=round(_original_risk_amount, 2),
                        ratio=round(risk_amount / _original_risk_amount, 3))
            _increment_counter(_get_redis(), "bahamut:counters:composite_floor_rejects")
            try:
                from bahamut.training.rejection_tracker import record_rejection
                record_rejection(asset=asset, strategy=strategy, direction=direction,
                                 signal_id=signal_id, reason_code="composite_floor",
                                 reason_detail=f"risk shrunk to {risk_amount:.2f} of {_original_risk_amount:.2f}")
            except Exception:
                pass
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
            regime=regime,
            substrategy=substrategy,
            data_mode=data_mode,
        )

        # ── Execute on exchange FIRST (Binance/Alpaca) ──
        # Position is only saved if exchange execution succeeds or is not required.
        _expected_platform = "internal"
        try:
            from bahamut.execution.router import execute_open as exec_open, _get_platform
            _expected_platform = _get_platform(asset, asset_class)
            exec_result = exec_open(
                asset=asset, asset_class=asset_class, direction=direction,
                size=pos.size, risk_amount=risk_amount,
            )
            pos.execution_platform = exec_result.get("platform", "internal")
            pos.exchange_order_id = exec_result.get("order_id", "")
            _status = exec_result.get("status", "unknown")
            # Phase 2 Item 4: capture canonical execution state on the position
            # so broker truth is preserved for PnL reporting and diagnostics.
            pos.client_order_id = exec_result.get("client_order_id", "") or ""
            pos.order_lifecycle = exec_result.get("lifecycle", "") or ""
            pos.fill_status = exec_result.get("fill_status", "") or ""
            pos.submitted_qty = float(exec_result.get("submitted_qty", 0) or 0)
            pos.filled_qty = float(exec_result.get("filled_qty", 0) or 0)
            pos.remaining_qty = float(exec_result.get("remaining_qty", 0) or 0)
            pos.avg_fill_price = float(exec_result.get("avg_fill_price",
                                                        exec_result.get("fill_price", 0)) or 0)
            pos.submitted_at = exec_result.get("submitted_at", "") or ""
            pos.accepted_at = exec_result.get("accepted_at", "") or ""
            pos.filled_at = exec_result.get("filled_at", "") or ""
            pos.reference_price = float(exec_result.get("reference_price", 0) or 0)
            pos.commission = float(exec_result.get("commission", 0) or 0)
            pos.commission_asset = exec_result.get("commission_asset", "") or ""
            pos.slippage_abs = float(exec_result.get("slippage_abs", 0) or 0)
            pos.slippage_pct = float(exec_result.get("slippage_pct", 0) or 0)
            logger.info("execution_route_result",
                         asset=asset, expected_platform=_expected_platform,
                         actual_platform=pos.execution_platform,
                         status=_status, lifecycle=pos.order_lifecycle,
                         fill_status=pos.fill_status,
                         filled_qty=pos.filled_qty, submitted_qty=pos.submitted_qty,
                         slippage_pct=round(pos.slippage_pct, 4),
                         order_id=pos.exchange_order_id[:20] if pos.exchange_order_id else "")

            if exec_result.get("fill_price") and exec_result["fill_price"] > 0:
                old_entry = pos.entry_price
                pos.entry_price = round(exec_result["fill_price"], 6)
                # Recompute size so realized risk matches intended risk
                pos.size = round(risk_amount / max(0.01, pos.entry_price * sl_pct), 8)
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
                            size_recomputed=pos.size,
                            order_id=pos.exchange_order_id)
                try:
                    from bahamut.execution.router import invalidate_platform_cache
                    invalidate_platform_cache(pos.execution_platform)
                except Exception:
                    pass

                # ── Broker-side bracket orders (SL/TP on exchange) ──
                if pos.execution_platform in ("binance", "binance_futures") and asset_class == "crypto":
                    try:
                        from bahamut.execution.binance_futures import place_bracket_orders
                        _side = "BUY" if direction == "LONG" else "SELL"
                        _brackets = place_bracket_orders(
                            asset=asset, side=_side, quantity=pos.size,
                            sl_price=pos.stop_price, tp_price=pos.tp_price,
                            entry_client_order_id=pos.exchange_order_id or str(_order_intent_id or ""),
                        )
                        pos.bracket_sl_order_id = str(_brackets.get("sl_order", {}).get("orderId", ""))
                        pos.bracket_tp_order_id = str(_brackets.get("tp_order", {}).get("orderId", ""))
                        logger.info("binance_brackets_placed",
                                    asset=asset, sl=pos.stop_price, tp=pos.tp_price,
                                    sl_id=pos.bracket_sl_order_id,
                                    tp_id=pos.bracket_tp_order_id)
                        if not pos.bracket_sl_order_id or not pos.bracket_tp_order_id:
                            try:
                                from bahamut.monitoring.telegram import send_alert
                                send_alert(f"⚠️ PARTIAL BRACKET COVERAGE: {asset} {direction} "
                                           f"sl_id={pos.bracket_sl_order_id or 'MISSING'} "
                                           f"tp_id={pos.bracket_tp_order_id or 'MISSING'}")
                            except Exception:
                                pass
                    except Exception as _br_err:
                        logger.error("binance_bracket_placement_failed",
                                     asset=asset, error=str(_br_err)[:200])

            # ── Wire OrderManager state machine ──
            if _order_intent_id:
                try:
                    from bahamut.execution.order_manager import OrderManager, OrderState
                    _mgr = OrderManager()
                    _lifecycle = exec_result.get("lifecycle", "")
                    if _lifecycle == "FILLED":
                        _mgr.record_fill(
                            intent_id=_order_intent_id,
                            fill_price=exec_result.get("fill_price", 0) or exec_result.get("avg_fill_price", 0),
                            fill_qty=exec_result.get("filled_qty", pos.size) or pos.size,
                            commission=float(exec_result.get("commission", 0) or 0),
                            broker_order_id=exec_result.get("order_id", ""),
                            platform=exec_result.get("platform", ""),
                            broker_response=exec_result.get("raw", {}),
                        )
                    elif _lifecycle in ("ACCEPTED", "SUBMITTED"):
                        _mgr.transition(_order_intent_id, OrderState.SUBMITTED,
                                        broker_response=exec_result.get("raw", {}))
                    elif _lifecycle in ("REJECTED", "ERROR"):
                        _mgr.transition(_order_intent_id, OrderState.REJECTED,
                                        {"error": exec_result.get("error", "")},
                                        broker_response=exec_result.get("raw", {}))
                except Exception as _sm_err:
                    logger.warning("order_state_machine_wire_failed",
                                   intent_id=_order_intent_id, error=str(_sm_err)[:100])

            # Abort guard: broker was expected but execution failed or fell back to internal
            if _status in ("error", "internal") and _expected_platform != "internal":
                # Broker was expected but execution failed or fell back to internal
                # Do NOT create a phantom internal-only position
                logger.warning("execution_failed_position_aborted",
                               asset=asset, strategy=strategy, direction=direction,
                               expected_platform=_expected_platform,
                               actual_platform=pos.execution_platform,
                               status=_status,
                               error=exec_result.get("error", "")[:100])
                _increment_counter(_get_redis(), "bahamut:counters:execution_failures")
                try:
                    from bahamut.training.rejection_tracker import record_rejection
                    record_rejection(asset=asset, strategy=strategy, direction=direction,
                                     signal_id=signal_id, reason_code="execution_error",
                                     reason_detail=f"status={_status}, platform_actual={pos.execution_platform}")
                except Exception:
                    pass
                return None
            # Final guard: if broker was expected but platform is still internal, abort
            if _expected_platform != "internal" and pos.execution_platform == "internal":
                logger.warning("execution_mirror_mismatch_aborted",
                               asset=asset, strategy=strategy, direction=direction,
                               expected_platform=_expected_platform,
                               actual_platform="internal", status=_status)
                _increment_counter(_get_redis(), "bahamut:counters:crypto_mirror_aborts")
                try:
                    from bahamut.training.rejection_tracker import record_rejection
                    record_rejection(asset=asset, strategy=strategy, direction=direction,
                                     signal_id=signal_id, reason_code="phantom_internal_abort",
                                     reason_detail="broker expected but fell back to internal")
                except Exception:
                    pass
                return None
        except Exception as e:
            # Mark order as SUBMISSION_UNKNOWN before aborting — the broker
            # may have received the order even though we got an exception.
            if _order_intent_id and _expected_platform != "internal":
                try:
                    from bahamut.execution.order_manager import OrderManager, OrderState
                    OrderManager().transition(_order_intent_id, OrderState.SUBMISSION_UNKNOWN,
                                              {"error": f"exception: {str(e)[:150]}"})
                except Exception:
                    pass
            if _expected_platform != "internal":
                logger.warning("execution_exception_position_aborted",
                               asset=asset, expected_platform=_expected_platform,
                               error=str(e)[:100])
                _increment_counter(_get_redis(), "bahamut:counters:execution_failures")
                try:
                    from bahamut.training.rejection_tracker import record_rejection
                    record_rejection(asset=asset, strategy=strategy, direction=direction,
                                     signal_id=signal_id, reason_code="execution_exception",
                                     reason_detail=str(e)[:200])
                except Exception:
                    pass
                return None
            logger.warning("exchange_execution_exception", asset=asset, error=str(e)[:100])

        # Save position only after exchange execution is resolved
        _save_position(pos)
        _opened_this_cycle.add(dedup_key)
        _opened_this_cycle.add(asset_key)
        open_training_position._opened_this_cycle = _opened_this_cycle

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

        # WebSocket live update (with production truth fields)
        try:
            from bahamut.ws.admin_live import publish_event
            publish_event("position_opened", {
                "mode": "training", "asset": asset, "strategy": strategy,
                "position_id": pos.position_id, "direction": direction,
                "entry": entry_price, "risk": risk_amount,
                "execution_confirmed": pos.execution_platform != "internal",
                "execution_platform": pos.execution_platform,
                "broker_order_id": pos.exchange_order_id,
                "data_mode": data_mode,
                "substrategy": substrategy,
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
    finally:
        if _lock_held_signal:
            try:
                from bahamut.execution.order_manager import OrderManager as _OMRel
                _OMRel().release_execution_lock(_lock_held_signal)
            except Exception:
                pass
# ═══════════════════════════════════════════

def force_close_all_training_positions(reason: str = "KILL_SWITCH") -> dict:
    """Emergency: force-close ALL open training positions.

    1. Fetches current price per asset
    2. Closes internal position (Redis + DB)
    3. Sends close order to exchange (Binance/Alpaca) if position was routed there
    4. Records trade with exit_reason = reason

    Returns summary dict.
    """
    positions = _load_positions()
    closed_count = 0
    errors = []
    closed_trades = []

    for pos in positions:
        try:
            # Get current market price for this asset
            close_price = 0.0
            try:
                from bahamut.data.binance_data import is_crypto, get_price
                if is_crypto(pos.asset):
                    close_price = get_price(pos.asset)
            except Exception:
                pass
            if close_price <= 0:
                close_price = pos.current_price if pos.current_price > 0 else pos.entry_price

            # Build exit bar
            bar = {
                "open": close_price, "high": close_price,
                "low": close_price, "close": close_price,
                "datetime": datetime.now(timezone.utc).isoformat(),
            }

            # Force SL/TP to ensure close triggers on next update
            if pos.direction == "LONG":
                pos.stop_price = close_price + 1  # guaranteed SL hit
            else:
                pos.stop_price = close_price - 1
            pos.max_hold_bars = 0  # force timeout

            # Close via normal path (handles exchange close + DB persist + learning)
            trades = update_positions_for_asset(pos.asset, bar)
            if trades:
                closed_trades.extend(trades)
                closed_count += 1
            else:
                # Fallback: direct removal if update didn't close it
                _remove_position(pos.position_id)
                closed_count += 1
                logger.warning("kill_switch_fallback_removal",
                               asset=pos.asset, position_id=pos.position_id)

        except Exception as e:
            errors.append({"asset": pos.asset, "error": str(e)[:100]})
            logger.error("kill_switch_close_failed",
                         asset=pos.asset, error=str(e)[:200])

    logger.warning("training_kill_switch_executed",
                     reason=reason, closed=closed_count,
                     errors=len(errors),
                     assets=[p.asset for p in positions])

    return {
        "closed": closed_count,
        "errors": errors,
        "total_positions": len(positions),
        "reason": reason,
    }


def get_open_positions() -> list[TrainingPosition]:
    """Return all currently open training positions."""
    return _load_positions()


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
            # Use broker-confirmed entry price if available (production truth),
            # otherwise fall back to candle-derived entry price (paper trading).
            canonical_entry = pos.avg_fill_price if pos.avg_fill_price > 0 else pos.entry_price

            if pos.direction == "LONG":
                pnl = (exit_price - canonical_entry) * pos.size
            else:
                pnl = (canonical_entry - exit_price) * pos.size

            pnl_pct = pnl / max(0.01, pos.risk_amount)

            trade = TrainingTrade(
                trade_id=str(uuid.uuid4())[:12],
                position_id=pos.position_id,
                asset=pos.asset,
                asset_class=pos.asset_class,
                strategy=pos.strategy,
                direction=pos.direction,
                entry_price=canonical_entry,  # broker-confirmed or candle fallback
                exit_price=round(exit_price, 6),
                stop_price=pos.stop_price,
                tp_price=pos.tp_price,
                size=pos.size,
                risk_amount=pos.risk_amount,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 4),
                return_pct=round(pnl / max(0.01, pos.entry_price * pos.size), 4),
                entry_time=pos.entry_time,
                exit_time=datetime.now(timezone.utc).isoformat(),
                exit_reason=exit_reason,
                bars_held=pos.bars_held,
                execution_type=pos.execution_type,
                confidence_score=pos.confidence_score,
                trigger_reason=pos.trigger_reason,
                regime=pos.regime,
                substrategy=pos.substrategy,
                data_mode=pos.data_mode,
                # Phase 5 Item 14: populate entry costs from position
                # (captured at open-time by open_training_position)
                entry_commission=pos.commission,
                entry_slippage_abs=pos.slippage_abs,
                entry_lifecycle=pos.order_lifecycle,
            )

            # ── Cancel broker-side brackets before closing ──
            if getattr(pos, "bracket_sl_order_id", "") or getattr(pos, "bracket_tp_order_id", ""):
                try:
                    from bahamut.execution.binance_futures import cancel_order, SYMBOL_MAP
                    _sym = SYMBOL_MAP.get(pos.asset, pos.asset.replace("USD", "USDT"))
                    if pos.bracket_sl_order_id:
                        cancel_order(_sym, pos.bracket_sl_order_id)
                    if pos.bracket_tp_order_id:
                        cancel_order(_sym, pos.bracket_tp_order_id)
                    logger.info("binance_brackets_cancelled",
                                asset=pos.asset, sl_id=pos.bracket_sl_order_id,
                                tp_id=pos.bracket_tp_order_id)
                except Exception as _bc_err:
                    logger.warning("binance_bracket_cancel_failed",
                                   asset=pos.asset, error=str(_bc_err)[:100])

            # ── BROKER-FIRST: execute close BEFORE removing local position ──
            # If broker close fails, position stays open locally so
            # reconciliation can detect and fix it. No phantom PnL persisted.
            _close_succeeded = False
            try:
                from bahamut.execution.router import execute_close as exec_close
                exec_result = exec_close(
                    asset=pos.asset, asset_class=pos.asset_class,
                    direction=pos.direction, size=pos.size,
                    entry_price=pos.entry_price,
                )
                _close_lifecycle = exec_result.get("lifecycle", exec_result.get("status", ""))
                trade.execution_platform = exec_result.get("platform", "internal")
                trade.exchange_order_id = exec_result.get("order_id", "")
                trade.exit_commission = float(exec_result.get("commission", 0) or 0)
                trade.exit_slippage_abs = float(exec_result.get("slippage_abs", 0) or 0)
                trade.exit_lifecycle = exec_result.get("order_lifecycle", "")

                if exec_result.get("fill_price") and exec_result["fill_price"] > 0:
                    # BROKER-TRUTH PnL — canonical
                    trade.exit_price = round(exec_result["fill_price"], 6)
                    entry_comm = float(pos.commission or 0)
                    exit_comm = float(exec_result.get("commission", 0) or 0)
                    total_comm = entry_comm + exit_comm
                    if pos.direction == "LONG":
                        trade.pnl = round((trade.exit_price - canonical_entry) * pos.size - total_comm, 2)
                    else:
                        trade.pnl = round((canonical_entry - trade.exit_price) * pos.size - total_comm, 2)
                    trade.pnl_pct = round(trade.pnl / max(0.01, pos.risk_amount), 4)
                    trade.return_pct = round(trade.pnl / max(0.01, canonical_entry * pos.size), 4)
                    logger.info("broker_truth_pnl_applied",
                                asset=pos.asset, platform=trade.execution_platform,
                                fill_price=trade.exit_price, entry=canonical_entry,
                                pnl=trade.pnl, commission=total_comm,
                                source="broker_fill")
                    try:
                        from bahamut.execution.router import invalidate_platform_cache
                        invalidate_platform_cache(trade.execution_platform)
                    except Exception:
                        pass
                    _close_succeeded = True
                    # Wire OrderManager close
                    try:
                        from bahamut.execution.order_manager import OrderManager
                        _mgr = OrderManager()
                        _intents = _mgr.get_open_intents(pos.asset)
                        for _it in _intents:
                            if _it.get("direction") == pos.direction:
                                _mgr.record_close(
                                    _it["id"], exit_price=trade.exit_price,
                                    exit_reason=exit_reason,
                                    exit_commission=exit_comm,
                                    broker_response=exec_result.get("raw", {}),
                                )
                                break
                    except Exception:
                        pass

                elif trade.execution_platform == "internal":
                    # Paper/internal mode — candle PnL is acceptable
                    trade.execution_platform = "paper"
                    _close_succeeded = True

                elif _close_lifecycle in ("ERROR", "REJECTED") or exec_result.get("error"):
                    logger.error("close_failed_position_remains_open",
                                 asset=pos.asset, position_id=pos.position_id,
                                 lifecycle=_close_lifecycle,
                                 error=exec_result.get("error", "")[:200])
                    try:
                        from bahamut.execution.order_manager import OrderManager, OrderState
                        _intents = OrderManager().get_open_intents(pos.asset)
                        for _it in _intents:
                            if _it.get("direction") == pos.direction:
                                OrderManager().transition(
                                    _it["id"], OrderState.RECONCILE_REQUIRED,
                                    {"error": f"close_rejected: {_close_lifecycle}"})
                                break
                    except Exception:
                        pass
                    continue  # DO NOT remove, DO NOT persist

                else:
                    trade.execution_platform = "paper"
                    _close_succeeded = True

            except Exception as e:
                logger.error("close_failed_position_remains_open",
                             asset=pos.asset, position_id=pos.position_id,
                             error=str(e)[:200])
                try:
                    from bahamut.execution.order_manager import OrderManager, OrderState
                    _intents = OrderManager().get_open_intents(pos.asset)
                    for _it in _intents:
                        if _it.get("direction") == pos.direction:
                            OrderManager().transition(
                                _it["id"], OrderState.RECONCILE_REQUIRED,
                                {"error": f"close_exception: {str(e)[:100]}"})
                            break
                except Exception:
                    pass
                continue  # DO NOT remove, DO NOT persist

            if not _close_succeeded:
                continue

            # ── Only now: remove local position + persist trade ──
            actually_removed = _remove_position(pos.position_id)
            if not actually_removed:
                logger.info("training_position_already_closed",
                            asset=pos.asset, position_id=pos.position_id)
                continue

            _already_closed.add(pos.position_id)
            update_positions_for_asset._already_closed = _already_closed

            _persist_trade(trade)
            _record_recent(trade)
            closed_trades.append(trade)

            # Invalidate risk engine cache (position count changed)
            try:
                from bahamut.training.risk_engine import invalidate_risk_cache
                invalidate_risk_cache()
            except Exception:
                pass

            # Set per-asset + per-strategy cooldown
            try:
                r = _get_redis()
                if r:
                    COOLDOWN_BY_STRATEGY = {"v5_base": 14400}
                    cd_time = COOLDOWN_BY_STRATEGY.get(pos.strategy, 1800)
                    if pos.execution_type == "crash_short" and trade.pnl < 0:
                        cs_loss_key = f"bahamut:crash_short:losses:{pos.asset}"
                        cs_count = int(r.get(cs_loss_key) or 0) + 1
                        r.setex(cs_loss_key, 86400, str(cs_count))
                        if cs_count >= 3:
                            cd_time = max(cd_time, 14400)
                        elif cs_count >= 2:
                            cd_time = max(cd_time, 7200)
                    elif pos.execution_type == "crash_short" and trade.pnl > 0:
                        r.delete(f"bahamut:crash_short:losses:{pos.asset}")
                    r.setex(f"bahamut:training:cooldown:{pos.asset}", cd_time, "1")
                    r.setex(f"bahamut:training:cooldown:{pos.asset}:{pos.strategy}", cd_time, "1")
            except Exception:
                pass

            logger.info("training_position_closed",
                        asset=pos.asset, strategy=pos.strategy,
                        pnl=trade.pnl, reason=exit_reason, bars=pos.bars_held)

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

            try:
                from bahamut.ws.admin_live import publish_event
                publish_event("position_closed", {
                    "mode": "training", "asset": pos.asset,
                    "strategy": pos.strategy, "position_id": pos.position_id,
                    "pnl": trade.pnl, "result": "WIN" if trade.pnl > 0.01 else ("FLAT" if abs(trade.pnl) < 0.01 else "LOSS"),
                    "exit_reason": exit_reason,
                    "execution_confirmed": trade.execution_platform not in ("internal", "paper"),
                    "execution_platform": trade.execution_platform,
                    "pnl_source": "broker_fill" if trade.execution_platform not in ("internal", "paper") else "candle",
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "total_costs": round((trade.entry_commission or 0) + (trade.exit_commission or 0), 4),
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
    # Phase 3 Item 7: ensure substrategy column exists (idempotent)
    _ensure_substrategy_column()
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
                 execution_type, confidence_score, trigger_reason, substrategy, data_mode)
                VALUES (:tid, :pid, :a, :ac, :s, :d, :ep, :xp, :sp, :tp, :sz, :ra,
                        :pnl, :pp, :et, :xt, :xr, :bh, :reg,
                        :exec_type, :conf, :trig, :sub, :dm)
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
                "sub": trade.substrategy or "",
                "dm": trade.data_mode or "live",
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
