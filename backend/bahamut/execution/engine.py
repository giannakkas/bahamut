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

    def on_new_bar(self, bar: dict, sleeve_equities: dict[str, float]):
        """
        Process a new bar:
          1. Fill pending orders at bar open
          2. Check open positions for SL/TP/timeout
        
        bar: {open, high, low, close, datetime, ...}
        sleeve_equities: {strategy_name: equity} for sizing
        """
        with self._lock:
            bar_time = bar.get("datetime", datetime.now(timezone.utc).isoformat())

            # 1. Fill pending orders
            for order in list(self.pending_orders):
                equity = sleeve_equities.get(order.strategy, 0)
                if equity <= 0:
                    order.status = OrderStatus.CANCELLED
                    self.pending_orders.remove(order)
                    continue

                # Size the position
                # We need a temporary entry price for sizing
                temp_entry = bar["open"]
                if order.direction == "LONG":
                    temp_sl = temp_entry * (1 - order.sl_pct)
                else:
                    temp_sl = temp_entry * (1 + order.sl_pct)

                sizing = size_position(equity, temp_entry, temp_sl,
                                       risk_pct=0.02)
                order.size = sizing["size"]
                order.risk_amount = sizing["risk_amount"]

                if order.size <= 0:
                    order.status = OrderStatus.CANCELLED
                    self.pending_orders.remove(order)
                    continue

                # Fill via broker
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
                            entry=position.entry_price,
                            sl=position.stop_price,
                            tp=position.tp_price,
                            size=position.size)

            # 2. Check open positions
            for pos in list(self.open_positions):
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
    return _engine
