"""
Paper Broker — deterministic paper trade execution.

- Entry at next bar open + slippage/spread
- SL/TP check with worst-case fill (if both hit same bar, fill SL)
- Timeout enforcement
"""
from dataclasses import dataclass
from bahamut.execution.models import Order, Position, ClosedTrade, OrderStatus, ExitReason
from datetime import datetime, timezone


@dataclass
class BrokerConfig:
    slippage_bps: float = 8.0    # Basis points
    spread_bps: float = 12.0
    mode: str = "paper"          # paper / live (future)


class PaperBroker:
    def __init__(self, config: BrokerConfig = None):
        self.config = config or BrokerConfig()

    def fill_order(self, order: Order, bar_open: float, bar_time: str = "") -> Position:
        """Fill a pending order at the bar open price with slippage/spread."""
        cfg = self.config
        slip = bar_open * (cfg.slippage_bps / 10_000)
        spread = bar_open * (cfg.spread_bps / 10_000)

        if order.direction == "LONG":
            fill_price = bar_open + slip + spread / 2
        else:
            fill_price = bar_open - slip - spread / 2

        # Compute SL/TP from fill price
        stop_price = fill_price * (1 - order.sl_pct) if order.direction == "LONG" \
            else fill_price * (1 + order.sl_pct)
        tp_price = fill_price * (1 + order.tp_pct) if order.direction == "LONG" \
            else fill_price * (1 - order.tp_pct)

        now = bar_time or datetime.now(timezone.utc).isoformat()

        return Position(
            order_id=order.order_id,
            strategy=order.strategy,
            asset=order.asset,
            direction=order.direction,
            status=OrderStatus.OPEN,
            entry_price=round(fill_price, 2),
            current_price=round(fill_price, 2),
            stop_price=round(stop_price, 2),
            tp_price=round(tp_price, 2),
            size=order.size,
            risk_amount=order.risk_amount,
            entry_time=now,
            entry_bar_idx=0,
            bars_held=0,
            max_hold_bars=order.max_hold_bars,
        )

    def check_exit(self, position: Position, high: float, low: float,
                   close: float, bars_held: int) -> ClosedTrade | None:
        """Check if position should be closed on this bar."""
        position.bars_held = bars_held
        position.update_price(close)

        exit_price = None
        exit_reason = None

        if position.direction == "LONG":
            sl_hit = low <= position.stop_price
            tp_hit = high >= position.tp_price
            if sl_hit and tp_hit:
                exit_price, exit_reason = position.stop_price, ExitReason.SL
            elif sl_hit:
                exit_price, exit_reason = position.stop_price, ExitReason.SL
            elif tp_hit:
                exit_price, exit_reason = position.tp_price, ExitReason.TP
        else:
            sl_hit = high >= position.stop_price
            tp_hit = low <= position.tp_price
            if sl_hit and tp_hit:
                exit_price, exit_reason = position.stop_price, ExitReason.SL
            elif sl_hit:
                exit_price, exit_reason = position.stop_price, ExitReason.SL
            elif tp_hit:
                exit_price, exit_reason = position.tp_price, ExitReason.TP

        # Timeout
        if exit_price is None and bars_held >= position.max_hold_bars:
            exit_price, exit_reason = close, ExitReason.TIMEOUT

        if exit_price is not None:
            return self._close(position, exit_price, exit_reason)
        return None

    def force_close(self, position: Position, price: float,
                    reason: str = "MANUAL") -> ClosedTrade:
        """Force close a position at given price."""
        return self._close(position, price, reason)

    def _close(self, pos: Position, exit_price: float, reason: str) -> ClosedTrade:
        reason_str = reason.value if hasattr(reason, 'value') else str(reason)
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * pos.size
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
        else:
            pnl = (pos.entry_price - exit_price) * pos.size
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price

        return ClosedTrade(
            order_id=pos.order_id,
            strategy=pos.strategy,
            asset=pos.asset,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=round(exit_price, 2),
            stop_price=pos.stop_price,
            tp_price=pos.tp_price,
            size=pos.size,
            risk_amount=pos.risk_amount,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc).isoformat(),
            exit_reason=reason_str,
            bars_held=pos.bars_held,
        )
