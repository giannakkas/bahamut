"""
Bahamut.AI — Production Order Manager

Implements:
  - Order lifecycle state machine (intent → fill → close)
  - Idempotent execution (no duplicate orders from retries/overlaps)
  - Full audit trail (every state transition logged to DB)
  - Unknown-state handling (submission_unknown → force reconciliation)

DB Tables (created idempotently on first use):
  - order_intents: every trade intent before submission
  - order_events: full lifecycle event log (audit trail)

Usage:
  from bahamut.execution.order_manager import OrderManager
  mgr = OrderManager()

  # Before submitting an order:
  intent = mgr.create_intent(asset, direction, size, signal_id, ...)
  if not intent:  # duplicate signal_id → already submitted
      return None

  # After broker response:
  mgr.record_submission(intent_id, exec_result)

  # After fill confirmation:
  mgr.record_fill(intent_id, fill_price, fill_qty, ...)

  # On close:
  mgr.record_close(intent_id, exit_price, exit_reason, ...)

This module is the SINGLE SOURCE OF TRUTH for order state.
Training engine and diagnostics read from here.
"""
import os
import json
import time
import uuid
import structlog
from datetime import datetime, timezone
from enum import Enum

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════
# ORDER STATES
# ═══════════════════════════════════════════════════════

class OrderState(str, Enum):
    """Strict order lifecycle states. Transitions are one-directional."""
    INTENT_CREATED = "intent_created"        # Signal approved, order built
    SUBMIT_PENDING = "submit_pending"        # About to send to broker
    SUBMITTED = "submitted"                  # Sent to broker, awaiting ack
    ACKNOWLEDGED = "acknowledged"            # Broker confirmed receipt
    PARTIALLY_FILLED = "partially_filled"    # Some qty filled
    FILLED = "filled"                        # Fully filled
    REJECTED = "rejected"                    # Broker rejected
    CANCELED = "canceled"                    # We canceled (or broker did)
    SUBMISSION_UNKNOWN = "submission_unknown" # Network error — don't know if submitted
    RECONCILE_REQUIRED = "reconcile_required" # Mismatch detected, needs manual/auto fix
    CLOSED = "closed"                        # Position fully closed
    ERROR = "error"                          # Unrecoverable error


class PositionState(str, Enum):
    """Position lifecycle states."""
    OPENING = "opening"         # Order submitted but not filled
    OPEN = "open"               # Fully filled, position active
    REDUCING = "reducing"       # Partial close in progress
    CLOSING = "closing"         # Close order submitted
    CLOSED = "closed"           # Fully closed
    UNKNOWN = "unknown"         # State unclear, needs reconciliation


# Valid state transitions
_VALID_TRANSITIONS = {
    OrderState.INTENT_CREATED: {OrderState.SUBMIT_PENDING, OrderState.CANCELED},
    OrderState.SUBMIT_PENDING: {OrderState.SUBMITTED, OrderState.SUBMISSION_UNKNOWN, OrderState.ERROR, OrderState.REJECTED},
    OrderState.SUBMITTED: {OrderState.ACKNOWLEDGED, OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.REJECTED, OrderState.CANCELED, OrderState.RECONCILE_REQUIRED},
    OrderState.ACKNOWLEDGED: {OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.REJECTED, OrderState.CANCELED, OrderState.RECONCILE_REQUIRED},
    OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCELED, OrderState.RECONCILE_REQUIRED},
    OrderState.FILLED: {OrderState.CLOSED, OrderState.RECONCILE_REQUIRED},
    OrderState.SUBMISSION_UNKNOWN: {OrderState.SUBMITTED, OrderState.ACKNOWLEDGED, OrderState.FILLED, OrderState.REJECTED, OrderState.RECONCILE_REQUIRED},
    OrderState.RECONCILE_REQUIRED: {OrderState.FILLED, OrderState.CLOSED, OrderState.CANCELED, OrderState.ERROR},
    OrderState.REJECTED: set(),  # Terminal
    OrderState.CANCELED: set(),  # Terminal
    OrderState.CLOSED: set(),    # Terminal
    OrderState.ERROR: {OrderState.RECONCILE_REQUIRED},  # Can recover via reconciliation
}

# DB migration flag
_TABLES_READY = False


def _get_redis():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2
        )
    except Exception:
        return None


def _ensure_tables():
    """Create order_intents and order_events tables if they don't exist.
    Idempotent — safe to call on every operation."""
    global _TABLES_READY
    if _TABLES_READY:
        return True
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS order_intents (
                    id VARCHAR(36) PRIMARY KEY,
                    signal_id VARCHAR(128) UNIQUE NOT NULL,
                    asset VARCHAR(32) NOT NULL,
                    asset_class VARCHAR(16) NOT NULL,
                    direction VARCHAR(8) NOT NULL,
                    strategy VARCHAR(64) NOT NULL,
                    substrategy VARCHAR(64) DEFAULT '',
                    intended_size FLOAT NOT NULL,
                    intended_price FLOAT DEFAULT 0,
                    sl_pct FLOAT DEFAULT 0,
                    tp_pct FLOAT DEFAULT 0,
                    risk_amount FLOAT DEFAULT 0,
                    order_state VARCHAR(32) NOT NULL DEFAULT 'intent_created',
                    position_state VARCHAR(32) NOT NULL DEFAULT 'opening',
                    client_order_id VARCHAR(128) DEFAULT '',
                    broker_order_id VARCHAR(128) DEFAULT '',
                    execution_platform VARCHAR(32) DEFAULT '',
                    filled_qty FLOAT DEFAULT 0,
                    remaining_qty FLOAT DEFAULT 0,
                    avg_fill_price FLOAT DEFAULT 0,
                    commission FLOAT DEFAULT 0,
                    slippage_abs FLOAT DEFAULT 0,
                    realized_pnl FLOAT DEFAULT 0,
                    exit_price FLOAT DEFAULT 0,
                    exit_reason VARCHAR(32) DEFAULT '',
                    error_message TEXT DEFAULT '',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    closed_at TIMESTAMP WITH TIME ZONE,
                    metadata JSONB DEFAULT '{}'
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS order_events (
                    id SERIAL PRIMARY KEY,
                    intent_id VARCHAR(36) NOT NULL REFERENCES order_intents(id),
                    event_type VARCHAR(64) NOT NULL,
                    from_state VARCHAR(32),
                    to_state VARCHAR(32),
                    details JSONB DEFAULT '{}',
                    broker_response JSONB DEFAULT '{}',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_order_intents_signal
                ON order_intents(signal_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_order_intents_asset_state
                ON order_intents(asset, order_state)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_order_events_intent
                ON order_events(intent_id)
            """))
            conn.commit()
        _TABLES_READY = True
        logger.info("order_manager_tables_ready")
        return True
    except Exception as e:
        logger.error("order_manager_table_creation_failed", error=str(e)[:200])
        return False


class OrderManager:
    """Production order lifecycle manager.

    Single point of truth for all order state transitions.
    Every mutation is persisted to DB + logged as an event.
    """

    def __init__(self):
        _ensure_tables()

    # ─────────────────────────────────────────
    # INTENT CREATION (Idempotency Gate)
    # ─────────────────────────────────────────

    def create_intent(
        self,
        asset: str,
        asset_class: str,
        direction: str,
        strategy: str,
        size: float,
        signal_id: str,
        risk_amount: float = 0,
        sl_pct: float = 0,
        tp_pct: float = 0,
        substrategy: str = "",
        intended_price: float = 0,
        metadata: dict = None,
    ) -> dict | None:
        """Create an order intent. Returns intent dict or None if duplicate.

        IDEMPOTENCY: signal_id is UNIQUE in the DB. If this signal was
        already processed (even if it failed), returns None. This prevents
        duplicate orders from retries, overlapping cycles, or multi-worker
        race conditions.
        """
        intent_id = str(uuid.uuid4())
        client_order_id = f"bah_{asset}_{int(time.time())}_{intent_id[:8]}"

        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                # Try to insert — UNIQUE constraint on signal_id prevents dupes
                try:
                    conn.execute(text("""
                        INSERT INTO order_intents
                        (id, signal_id, asset, asset_class, direction, strategy,
                         substrategy, intended_size, intended_price,
                         sl_pct, tp_pct, risk_amount,
                         order_state, position_state, client_order_id, metadata)
                        VALUES (:id, :sid, :a, :ac, :d, :s, :sub, :sz, :ip,
                                :sl, :tp, :ra, :os, :ps, :coid, :meta)
                    """), {
                        "id": intent_id, "sid": signal_id,
                        "a": asset, "ac": asset_class,
                        "d": direction, "s": strategy, "sub": substrategy,
                        "sz": size, "ip": intended_price,
                        "sl": sl_pct, "tp": tp_pct, "ra": risk_amount,
                        "os": OrderState.INTENT_CREATED.value,
                        "ps": PositionState.OPENING.value,
                        "coid": client_order_id,
                        "meta": json.dumps(metadata or {}),
                    })
                    conn.commit()
                except Exception as dup_err:
                    if "unique" in str(dup_err).lower() or "duplicate" in str(dup_err).lower():
                        logger.info("order_intent_duplicate_blocked",
                                    signal_id=signal_id, asset=asset)
                        return None
                    raise

            # Log the creation event
            self._log_event(intent_id, "intent_created", None,
                            OrderState.INTENT_CREATED.value,
                            {"signal_id": signal_id, "size": size})

            logger.info("order_intent_created",
                        intent_id=intent_id, signal_id=signal_id,
                        asset=asset, direction=direction, size=size)

            return {
                "intent_id": intent_id,
                "signal_id": signal_id,
                "client_order_id": client_order_id,
                "asset": asset,
                "direction": direction,
                "size": size,
            }
        except Exception as e:
            logger.error("order_intent_creation_failed",
                         signal_id=signal_id, error=str(e)[:200])
            return None

    # ─────────────────────────────────────────
    # STATE TRANSITIONS
    # ─────────────────────────────────────────

    def transition(self, intent_id: str, new_state: OrderState,
                   details: dict = None, broker_response: dict = None) -> bool:
        """Transition an order to a new state. Returns True if valid.

        Validates the transition is legal, persists it, and logs the event.
        Invalid transitions are REJECTED AND LOGGED — they don't silently fail.
        """
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                # Read current state
                row = conn.execute(text(
                    "SELECT order_state FROM order_intents WHERE id = :id"
                ), {"id": intent_id}).mappings().first()
                if not row:
                    logger.error("order_transition_unknown_intent", intent_id=intent_id)
                    return False

                current = OrderState(row["order_state"])
                valid_next = _VALID_TRANSITIONS.get(current, set())
                if new_state not in valid_next:
                    logger.error("order_transition_invalid",
                                 intent_id=intent_id,
                                 current=current.value,
                                 attempted=new_state.value,
                                 valid=sorted(s.value for s in valid_next))
                    self._log_event(intent_id, "invalid_transition", current.value,
                                    new_state.value,
                                    {"error": f"invalid: {current.value} → {new_state.value}"})
                    return False

                # Apply transition
                updates = {"os": new_state.value, "id": intent_id}
                sql_parts = ["order_state = :os", "updated_at = NOW()"]

                # Terminal states
                if new_state in (OrderState.CLOSED, OrderState.CANCELED, OrderState.REJECTED):
                    sql_parts.append("closed_at = NOW()")

                # Error message
                if details and details.get("error"):
                    sql_parts.append("error_message = :err")
                    updates["err"] = str(details["error"])[:500]

                conn.execute(text(
                    f"UPDATE order_intents SET {', '.join(sql_parts)} WHERE id = :id"
                ), updates)
                conn.commit()

            # Log the event
            self._log_event(intent_id, f"transition_{new_state.value}",
                            current.value, new_state.value,
                            details, broker_response)

            logger.info("order_state_transition",
                        intent_id=intent_id,
                        from_state=current.value,
                        to_state=new_state.value)
            return True
        except Exception as e:
            logger.error("order_transition_failed",
                         intent_id=intent_id, error=str(e)[:200])
            return False

    # ─────────────────────────────────────────
    # FILL RECORDING (Broker Truth)
    # ─────────────────────────────────────────

    def record_fill(
        self,
        intent_id: str,
        fill_price: float,
        fill_qty: float,
        total_filled: float = 0,
        remaining: float = 0,
        commission: float = 0,
        broker_order_id: str = "",
        platform: str = "",
        broker_response: dict = None,
    ) -> bool:
        """Record a fill from the broker. This is the CANONICAL price source.

        Handles both full and partial fills:
          - Partial: updates filled_qty, remaining_qty, avg_fill_price
          - Full: transitions to FILLED state, sets position to OPEN

        avg_fill_price is computed as weighted average across all fills.
        """
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT order_state, filled_qty, avg_fill_price, intended_size "
                    "FROM order_intents WHERE id = :id"
                ), {"id": intent_id}).mappings().first()
                if not row:
                    return False

                prev_filled = float(row["filled_qty"] or 0)
                prev_avg = float(row["avg_fill_price"] or 0)
                intended = float(row["intended_size"] or 0)

                # Compute new weighted average fill price
                new_total_filled = prev_filled + fill_qty
                if new_total_filled > 0:
                    new_avg = ((prev_avg * prev_filled) + (fill_price * fill_qty)) / new_total_filled
                else:
                    new_avg = fill_price

                new_remaining = remaining if remaining > 0 else max(0, intended - new_total_filled)
                is_fully_filled = new_remaining < (intended * 0.001)  # within 0.1% tolerance

                # Determine new state
                if is_fully_filled:
                    new_order_state = OrderState.FILLED
                    new_pos_state = PositionState.OPEN
                else:
                    new_order_state = OrderState.PARTIALLY_FILLED
                    new_pos_state = PositionState.OPENING

                conn.execute(text("""
                    UPDATE order_intents SET
                        order_state = :os, position_state = :ps,
                        filled_qty = :fq, remaining_qty = :rq,
                        avg_fill_price = :afp, commission = commission + :comm,
                        broker_order_id = COALESCE(NULLIF(:boid, ''), broker_order_id),
                        execution_platform = COALESCE(NULLIF(:plat, ''), execution_platform),
                        updated_at = NOW()
                    WHERE id = :id
                """), {
                    "os": new_order_state.value, "ps": new_pos_state.value,
                    "fq": new_total_filled, "rq": new_remaining,
                    "afp": round(new_avg, 8), "comm": commission,
                    "boid": broker_order_id, "plat": platform,
                    "id": intent_id,
                })
                conn.commit()

            self._log_event(intent_id, "fill", row["order_state"],
                            new_order_state.value, {
                                "fill_price": fill_price,
                                "fill_qty": fill_qty,
                                "total_filled": new_total_filled,
                                "remaining": new_remaining,
                                "avg_price": round(new_avg, 8),
                                "commission": commission,
                                "is_fully_filled": is_fully_filled,
                            }, broker_response)

            logger.info("order_fill_recorded",
                        intent_id=intent_id,
                        fill_price=fill_price, fill_qty=fill_qty,
                        total_filled=new_total_filled,
                        fully_filled=is_fully_filled)
            return True
        except Exception as e:
            logger.error("order_fill_record_failed",
                         intent_id=intent_id, error=str(e)[:200])
            return False

    # ─────────────────────────────────────────
    # CLOSE RECORDING (Broker Truth for Exit)
    # ─────────────────────────────────────────

    def record_close(
        self,
        intent_id: str,
        exit_price: float,
        exit_reason: str,
        exit_commission: float = 0,
        exit_slippage: float = 0,
        broker_response: dict = None,
    ) -> dict | None:
        """Record position close. Computes CANONICAL PnL from broker fills.

        PnL = (exit_price - avg_fill_price) * filled_qty * direction_mult
        This NEVER uses candle prices. exit_price comes from broker fill.

        Returns trade result dict or None on failure.
        """
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT * FROM order_intents WHERE id = :id"
                ), {"id": intent_id}).mappings().first()
                if not row:
                    return None

                entry_price = float(row["avg_fill_price"] or 0)
                filled_qty = float(row["filled_qty"] or 0)
                direction = row["direction"]
                entry_commission = float(row["commission"] or 0)

                if entry_price <= 0 or filled_qty <= 0:
                    logger.error("order_close_no_fill_data",
                                 intent_id=intent_id,
                                 entry_price=entry_price,
                                 filled_qty=filled_qty)
                    return None

                # CANONICAL PnL from broker fills — NEVER from candle prices
                if direction == "LONG":
                    gross_pnl = (exit_price - entry_price) * filled_qty
                else:
                    gross_pnl = (entry_price - exit_price) * filled_qty

                total_costs = entry_commission + exit_commission + exit_slippage
                net_pnl = gross_pnl - total_costs

                conn.execute(text("""
                    UPDATE order_intents SET
                        order_state = :os, position_state = :ps,
                        exit_price = :xp, exit_reason = :xr,
                        realized_pnl = :pnl,
                        commission = commission + :xcomm,
                        slippage_abs = slippage_abs + :xslip,
                        closed_at = NOW(), updated_at = NOW()
                    WHERE id = :id
                """), {
                    "os": OrderState.CLOSED.value,
                    "ps": PositionState.CLOSED.value,
                    "xp": exit_price, "xr": exit_reason,
                    "pnl": round(net_pnl, 4),
                    "xcomm": exit_commission, "xslip": exit_slippage,
                    "id": intent_id,
                })
                conn.commit()

            result = {
                "intent_id": intent_id,
                "asset": row["asset"],
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "filled_qty": filled_qty,
                "gross_pnl": round(gross_pnl, 4),
                "net_pnl": round(net_pnl, 4),
                "total_costs": round(total_costs, 4),
                "exit_reason": exit_reason,
                "risk_amount": float(row["risk_amount"] or 0),
                "r_multiple": round(net_pnl / max(float(row["risk_amount"] or 1), 0.01), 4),
            }

            self._log_event(intent_id, "close", OrderState.FILLED.value,
                            OrderState.CLOSED.value, result, broker_response)

            logger.info("order_closed",
                        intent_id=intent_id, asset=row["asset"],
                        net_pnl=round(net_pnl, 2), exit_reason=exit_reason)
            return result
        except Exception as e:
            logger.error("order_close_record_failed",
                         intent_id=intent_id, error=str(e)[:200])
            return None

    # ─────────────────────────────────────────
    # QUERY METHODS
    # ─────────────────────────────────────────

    def get_open_intents(self, asset: str = None) -> list[dict]:
        """Get all intents with open positions (FILLED state, OPEN position)."""
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            where = "WHERE position_state = 'open'"
            params = {}
            if asset:
                where += " AND asset = :asset"
                params["asset"] = asset
            with sync_engine.connect() as conn:
                rows = conn.execute(text(
                    f"SELECT * FROM order_intents {where} ORDER BY created_at DESC"
                ), params).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_intent_by_signal(self, signal_id: str) -> dict | None:
        """Look up intent by signal_id (for idempotency checks)."""
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT * FROM order_intents WHERE signal_id = :sid"
                ), {"sid": signal_id}).mappings().first()
                return dict(row) if row else None
        except Exception:
            return None

    def get_intents_needing_reconciliation(self) -> list[dict]:
        """Get intents in unknown/error states that need reconciliation."""
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT * FROM order_intents
                    WHERE order_state IN ('submission_unknown', 'reconcile_required',
                                          'submit_pending', 'submitted', 'acknowledged')
                    ORDER BY created_at ASC
                """)).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_audit_trail(self, intent_id: str) -> list[dict]:
        """Full event history for an order."""
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT * FROM order_events WHERE intent_id = :id ORDER BY created_at ASC"
                ), {"id": intent_id}).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # ─────────────────────────────────────────
    # IDEMPOTENCY LOCK (Redis-based, for multi-worker)
    # ─────────────────────────────────────────

    def acquire_execution_lock(self, asset: str, direction: str,
                                ttl: int = 30) -> bool:
        """Acquire a Redis lock before submitting an order.
        Prevents two workers from opening the same trade simultaneously.
        Returns True if lock acquired."""
        r = _get_redis()
        if not r:
            return True  # No Redis → allow (DB uniqueness is the backup)
        lock_key = f"bahamut:exec_lock:{asset}:{direction}"
        try:
            acquired = r.set(lock_key, "1", nx=True, ex=ttl)
            return bool(acquired)
        except Exception:
            return True

    def release_execution_lock(self, asset: str, direction: str):
        """Release execution lock after order processing completes."""
        r = _get_redis()
        if not r:
            return
        lock_key = f"bahamut:exec_lock:{asset}:{direction}"
        try:
            r.delete(lock_key)
        except Exception:
            pass

    # ─────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────

    def _log_event(self, intent_id: str, event_type: str,
                   from_state: str | None, to_state: str | None,
                   details: dict = None, broker_response: dict = None):
        """Persist an event to the audit trail."""
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO order_events
                    (intent_id, event_type, from_state, to_state, details, broker_response)
                    VALUES (:iid, :et, :fs, :ts, :d, :br)
                """), {
                    "iid": intent_id, "et": event_type,
                    "fs": from_state, "ts": to_state,
                    "d": json.dumps(details or {}, default=str),
                    "br": json.dumps(broker_response or {}, default=str),
                })
                conn.commit()
        except Exception as e:
            # Audit trail failure must not crash execution
            logger.warning("order_event_log_failed",
                           intent_id=intent_id, event_type=event_type,
                           error=str(e)[:100])
