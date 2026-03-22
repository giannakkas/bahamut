"""
Bahamut Execution Engine

Central orchestrator for paper/live trading:
  1. Accept signals from strategy modules
  2. Size positions by risk
  3. Submit to paper broker
  4. Monitor open positions on each bar
  5. Track all orders, positions, trades

Thread-safe singleton — all state in memory + periodically persisted to DB.
"""
import structlog
from datetime import datetime, timezone
from typing import Optional
from threading import Lock

from bahamut.execution.models import Order, Position, ClosedTrade, OrderStatus
from bahamut.execution.sizer import size_position
from bahamut.execution.paper_broker import PaperBroker, BrokerConfig
from bahamut.strategies.base import Signal

logger = structlog.get_logger()


class ExecutionEngine:
    """Singleton execution engine managing all paper trading state."""

    def __init__(self):
        self.broker = PaperBroker(BrokerConfig())
        self.pending_orders: list[Order] = []
        self.open_positions: list[Position] = []
        self.closed_trades: list[ClosedTrade] = []
        self.all_orders: list[Order] = []
        self._lock = Lock()
        self._processed_signals: set[str] = set()  # Idempotency
        self._kill_switch = False

    # ═══════════════════════════════════════════════════════
    # SIGNAL INTAKE
    # ═══════════════════════════════════════════════════════

    def submit_signal(self, signal: Signal, sleeve_equity: float) -> Optional[Order]:
        """
        Accept a strategy signal, size it, create a pending order.
        Returns the Order or None if rejected.
        """
        with self._lock:
            # Kill switch
            if self._kill_switch:
                logger.warning("signal_rejected_kill_switch", strategy=signal.strategy)
                return None

            # Idempotency: don't process same signal twice
            if signal.signal_id in self._processed_signals:
                logger.info("signal_duplicate", signal_id=signal.signal_id)
                return None
            self._processed_signals.add(signal.signal_id)

            # Check if strategy already has open position FOR THIS ASSET
            for pos in self.open_positions:
                if pos.strategy == signal.strategy and pos.asset == signal.asset \
                   and pos.status == OrderStatus.OPEN:
                    logger.info("signal_rejected_existing_position",
                                strategy=signal.strategy, asset=signal.asset)
                    return None

            # Check if strategy already has pending order FOR THIS ASSET
            for o in self.pending_orders:
                if o.strategy == signal.strategy and o.asset == signal.asset \
                   and o.status == OrderStatus.PENDING:
                    logger.info("signal_rejected_pending_order",
                                strategy=signal.strategy, asset=signal.asset)
                    return None

            # Create order (entry_price=0 means fill at next open)
            order = Order(
                strategy=signal.strategy,
                asset=signal.asset,
                direction=signal.direction,
                status=OrderStatus.PENDING,
                signal_time=signal.timestamp,
                signal_id=signal.signal_id,
                sl_pct=signal.sl_pct,
                tp_pct=signal.tp_pct,
                max_hold_bars=signal.max_hold_bars,
            )

            self.pending_orders.append(order)
            self.all_orders.append(order)
            logger.info("order_created", order_id=order.order_id,
                        strategy=signal.strategy, direction=signal.direction)
            return order

    # ═══════════════════════════════════════════════════════
    # BAR PROCESSING (called each new bar)
    # ═══════════════════════════════════════════════════════

    def on_new_bar(self, bar: dict, sleeve_equities: dict[str, float],
                   asset: str = ""):
        """
        Process a new bar for a specific asset:
          1. Fill pending orders FOR THIS ASSET at bar open
          2. Check open positions FOR THIS ASSET for SL/TP/timeout
        
        bar: {open, high, low, close, datetime, ...}
        sleeve_equities: {strategy_name: equity} for sizing
        asset: which asset this bar belongs to (e.g. "BTCUSD")
        """
        with self._lock:
            bar_time = bar.get("datetime", datetime.now(timezone.utc).isoformat())

            # 1. Fill pending orders FOR THIS ASSET ONLY
            for order in list(self.pending_orders):
                if asset and order.asset != asset:
                    continue  # Skip orders for other assets

                equity = sleeve_equities.get(order.strategy, 0)
                if equity <= 0:
                    order.status = OrderStatus.CANCELLED
                    self.pending_orders.remove(order)
                    continue

                temp_entry = bar["open"]
                if order.direction == "LONG":
                    temp_sl = temp_entry * (1 - order.sl_pct)
                else:
                    temp_sl = temp_entry * (1 + order.sl_pct)

                sizing = size_position(equity, temp_entry, temp_sl, risk_pct=0.02)
                order.size = sizing["size"]
                order.risk_amount = sizing["risk_amount"]

                if order.size <= 0:
                    order.status = OrderStatus.CANCELLED
                    self.pending_orders.remove(order)
                    continue

                position = self.broker.fill_order(order, bar["open"], bar_time)
                position.size = order.size
                position.risk_amount = order.risk_amount

                order.status = OrderStatus.OPEN
                order.fill_time = bar_time
                order.entry_price = position.entry_price
                order.stop_price = position.stop_price
                order.tp_price = position.tp_price

                self.open_positions.append(position)
                self.pending_orders.remove(order)

                logger.info("position_opened",
                            order_id=order.order_id,
                            strategy=order.strategy,
                            asset=order.asset,
                            entry=position.entry_price,
                            sl=position.stop_price,
                            tp=position.tp_price,
                            size=position.size)

                # Fire trade opened alert
                try:
                    from bahamut.monitoring.alerts import fire_trade_alert
                    fire_trade_alert({"asset": order.asset, "strategy": order.strategy,
                                      "direction": order.direction, "entry_price": position.entry_price}, "opened")
                except Exception:
                    pass

            # 2. Check open positions FOR THIS ASSET ONLY
            for pos in list(self.open_positions):
                if asset and pos.asset != asset:
                    continue  # Don't apply BTC prices to ETH positions!

                if pos.status != OrderStatus.OPEN:
                    continue

                pos.bars_held += 1
                closed = self.broker.check_exit(
                    pos, bar["high"], bar["low"], bar["close"], pos.bars_held)

                if closed:
                    pos.status = OrderStatus.CLOSED
                    self.open_positions.remove(pos)
                    self.closed_trades.append(closed)

                    # Update corresponding order
                    for o in self.all_orders:
                        if o.order_id == closed.order_id:
                            o.status = OrderStatus.CLOSED
                            break

                    logger.info("position_closed",
                                order_id=closed.order_id,
                                strategy=closed.strategy,
                                reason=closed.exit_reason,
                                pnl=closed.pnl,
                                bars=closed.bars_held)

                    # Fire trade closed alert
                    try:
                        from bahamut.monitoring.alerts import fire_trade_alert
                        fire_trade_alert({"asset": closed.asset, "strategy": closed.strategy,
                                          "direction": closed.direction, "pnl": closed.pnl,
                                          "exit_reason": closed.exit_reason}, "closed")
                    except Exception:
                        pass
                else:
                    pos.update_price(bar["close"])

    # ═══════════════════════════════════════════════════════
    # KILL SWITCH
    # ═══════════════════════════════════════════════════════

    def activate_kill_switch(self, price: float):
        """Close all positions and block new trades."""
        with self._lock:
            self._kill_switch = True
            closed_count = 0
            for pos in list(self.open_positions):
                trade = self.broker.force_close(pos, price, "KILL_SWITCH")
                self.closed_trades.append(trade)
                self.open_positions.remove(pos)
                closed_count += 1

            for order in list(self.pending_orders):
                order.status = OrderStatus.CANCELLED
                self.pending_orders.remove(order)

            logger.warning("kill_switch_activated", closed=closed_count)
            return closed_count

    def resume_trading(self):
        with self._lock:
            self._kill_switch = False
            logger.info("trading_resumed")

    @property
    def is_kill_switch_active(self):
        return self._kill_switch

    # ═══════════════════════════════════════════════════════
    # QUERIES
    # ═══════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        with self._lock:
            wins = [t for t in self.closed_trades if t.pnl > 0]
            losses = [t for t in self.closed_trades if t.pnl <= 0]
            total_pnl = sum(t.pnl for t in self.closed_trades)
            total_unrealized = sum(p.unrealized_pnl for p in self.open_positions)

            return {
                "pending_orders": len(self.pending_orders),
                "open_positions": len(self.open_positions),
                "closed_trades": len(self.closed_trades),
                "total_realized_pnl": round(total_pnl, 2),
                "total_unrealized_pnl": round(total_unrealized, 2),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / max(1, len(self.closed_trades)), 4),
                "kill_switch": self._kill_switch,
            }

    def get_open_positions_list(self) -> list[dict]:
        return [
            {
                "order_id": p.order_id, "strategy": p.strategy, "asset": p.asset,
                "direction": p.direction, "entry_price": p.entry_price,
                "current_price": p.current_price, "stop_price": p.stop_price,
                "tp_price": p.tp_price, "size": p.size,
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct * 100, 2),
                "bars_held": p.bars_held, "max_hold_bars": p.max_hold_bars,
                "entry_time": p.entry_time,
            }
            for p in self.open_positions
        ]

    def get_closed_trades_list(self) -> list[dict]:
        return [
            {
                "trade_id": t.trade_id, "order_id": t.order_id,
                "strategy": t.strategy, "asset": t.asset,
                "direction": t.direction,
                "entry_price": t.entry_price, "exit_price": t.exit_price,
                "stop_price": t.stop_price, "tp_price": t.tp_price,
                "size": t.size, "pnl": t.pnl,
                "pnl_pct": round(t.pnl_pct * 100, 2),
                "exit_reason": t.exit_reason, "bars_held": t.bars_held,
                "entry_time": t.entry_time, "exit_time": t.exit_time,
            }
            for t in self.closed_trades
        ]

    def get_pending_orders_list(self) -> list[dict]:
        return [
            {
                "order_id": o.order_id, "strategy": o.strategy, "asset": o.asset,
                "direction": o.direction, "status": o.status,
                "signal_time": o.signal_time, "signal_id": o.signal_id,
            }
            for o in self.pending_orders
        ]

    def get_strategy_pnl(self, strategy: str) -> float:
        return sum(t.pnl for t in self.closed_trades if t.strategy == strategy)

    def get_strategy_unrealized(self, strategy: str) -> float:
        return sum(p.unrealized_pnl for p in self.open_positions if p.strategy == strategy)


# ── Singleton ──
_engine: Optional[ExecutionEngine] = None

def get_execution_engine() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine()
        _reconcile_from_db(_engine)
    return _engine


def _reconcile_from_db(engine: ExecutionEngine):
    """Startup reconciliation: rebuild execution state from canonical DB records.

    Loads:
      1. Open orders/positions from v7_orders WHERE status = 'OPEN'
      2. Closed trades from v7_trades (for performance metrics)
      3. Processed signal_ids from v7_orders (for idempotency)

    This ensures restart cannot cause:
      - Orphan positions (open in DB but unknown to engine)
      - Duplicate signals (signal_id set is empty after restart)
      - Empty performance tab (closed_trades list is empty)
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text

        with sync_engine.connect() as conn:
            # 1. Load open positions
            open_rows = conn.execute(text("""
                SELECT order_id, strategy_name, asset, direction, status,
                       entry_price, stop_price, tp_price, size, risk_amount,
                       fill_time, sl_pct, tp_pct, max_hold_bars, signal_id
                FROM v7_orders WHERE status = 'OPEN'
                ORDER BY fill_time
            """)).mappings().all()

            for r in open_rows:
                pos = Position(
                    order_id=r["order_id"],
                    strategy=r["strategy_name"],
                    asset=r["asset"],
                    direction=r["direction"],
                    status=OrderStatus.OPEN,
                    entry_price=float(r["entry_price"] or 0),
                    current_price=float(r["entry_price"] or 0),
                    stop_price=float(r["stop_price"] or 0),
                    tp_price=float(r["tp_price"] or 0),
                    size=float(r["size"] or 0),
                    risk_amount=float(r["risk_amount"] or 0),
                    entry_time=str(r["fill_time"] or ""),
                    max_hold_bars=int(r["max_hold_bars"] or 30),
                )
                engine.open_positions.append(pos)

                # Reconstruct order for all_orders
                order = Order(
                    order_id=r["order_id"],
                    strategy=r["strategy_name"],
                    asset=r["asset"],
                    direction=r["direction"],
                    status=OrderStatus.OPEN,
                    signal_id=r["signal_id"] or "",
                    entry_price=float(r["entry_price"] or 0),
                    stop_price=float(r["stop_price"] or 0),
                    tp_price=float(r["tp_price"] or 0),
                    size=float(r["size"] or 0),
                    risk_amount=float(r["risk_amount"] or 0),
                    fill_time=str(r["fill_time"] or ""),
                    sl_pct=float(r["sl_pct"] or 0),
                    tp_pct=float(r["tp_pct"] or 0),
                    max_hold_bars=int(r["max_hold_bars"] or 30),
                )
                engine.all_orders.append(order)

            # 2. Load closed trades (last 200 for performance metrics)
            trade_rows = conn.execute(text("""
                SELECT trade_id, order_id, strategy_name, asset, direction,
                       entry_price, exit_price, stop_price, tp_price, size,
                       risk_amount, pnl, pnl_pct, entry_time, exit_time,
                       exit_reason, bars_held
                FROM v7_trades ORDER BY exit_time DESC LIMIT 200
            """)).mappings().all()

            for r in reversed(trade_rows):  # oldest first
                trade = ClosedTrade(
                    trade_id=r["trade_id"],
                    order_id=r["order_id"],
                    strategy=r["strategy_name"],
                    asset=r["asset"],
                    direction=r["direction"],
                    entry_price=float(r["entry_price"] or 0),
                    exit_price=float(r["exit_price"] or 0),
                    stop_price=float(r["stop_price"] or 0),
                    tp_price=float(r["tp_price"] or 0),
                    size=float(r["size"] or 0),
                    risk_amount=float(r["risk_amount"] or 0),
                    pnl=float(r["pnl"] or 0),
                    pnl_pct=float(r["pnl_pct"] or 0),
                    entry_time=str(r["entry_time"] or ""),
                    exit_time=str(r["exit_time"] or ""),
                    exit_reason=str(r["exit_reason"] or ""),
                    bars_held=int(r["bars_held"] or 0),
                )
                engine.closed_trades.append(trade)

            # 3. Load all signal_ids for idempotency
            sig_rows = conn.execute(text(
                "SELECT signal_id FROM v7_orders WHERE signal_id IS NOT NULL AND signal_id != ''"
            )).all()
            for r in sig_rows:
                engine._processed_signals.add(r[0])

        logger.info("engine_reconciled_from_db",
                     open_positions=len(engine.open_positions),
                     closed_trades=len(engine.closed_trades),
                     signal_ids=len(engine._processed_signals))

    except Exception as e:
        logger.warning("engine_reconciliation_failed", error=str(e),
                       note="engine starts empty — first cycle will populate from live data")
