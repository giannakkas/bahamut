"""
Bahamut Test Trade Mode

Allows operator to create a synthetic paper trade to verify the full lifecycle:
  signal → order → position → close → performance update

SAFETY:
  - Clearly marked as TEST in all records
  - Only available to super_admin
  - Does NOT affect production strategy logic
  - Uses the real ExecutionEngine so lifecycle is verified end-to-end
"""
import structlog
from datetime import datetime, timezone

from bahamut.execution.engine import get_execution_engine
from bahamut.execution.models import ClosedTrade
from bahamut.portfolio.manager import get_portfolio_manager
from bahamut.strategies.base import Signal

logger = structlog.get_logger()


def create_test_trade(
    asset: str = "BTCUSD",
    strategy: str = "test_trade",
    direction: str = "LONG",
    entry_price: float = 0.0,
) -> dict:
    """
    Create a test trade through the real execution pipeline.

    If entry_price=0, uses a synthetic bar at current market price.
    Returns the full lifecycle state after creation.
    """
    engine = get_execution_engine()
    pm = get_portfolio_manager()

    # Get current price if not provided
    if entry_price <= 0:
        try:
            from bahamut.execution.v7_orchestrator import _fetch_candles
            candles = _fetch_candles(asset, count=5)
            if candles:
                entry_price = float(candles[-1].get("close", 0))
        except Exception:
            pass
        if entry_price <= 0:
            entry_price = 68000.0 if "BTC" in asset else 2000.0

    # Create signal
    signal = Signal(
        strategy=f"TEST_{strategy}",
        asset=asset,
        direction=direction,
        sl_pct=0.03,       # 3% SL
        tp_pct=0.06,       # 6% TP
        max_hold_bars=10,
        quality=1.0,
        reason="TEST TRADE — operator verification",
    )

    # Submit signal to engine
    order = engine.submit_signal(signal, pm.total_equity)
    if not order:
        return {
            "status": "REJECTED",
            "reason": "Signal rejected — kill switch active or duplicate",
        }

    # Create synthetic bar to fill the order immediately
    bar = {
        "open": entry_price,
        "high": entry_price * 1.001,
        "low": entry_price * 0.999,
        "close": entry_price,
        "datetime": datetime.now(timezone.utc).isoformat(),
    }

    sleeve = {f"TEST_{strategy}": pm.total_equity * 0.1}  # 10% sleeve
    engine.on_new_bar(bar, sleeve, asset=asset)

    # Find the position
    test_positions = [p for p in engine.open_positions if p.strategy == f"TEST_{strategy}"]

    if test_positions:
        pos = test_positions[0]
        logger.info("test_trade_opened",
                     asset=asset, strategy=f"TEST_{strategy}",
                     entry=pos.entry_price, sl=pos.stop_price, tp=pos.tp_price)
        return {
            "status": "OPENED",
            "order_id": order.order_id,
            "position": {
                "asset": pos.asset,
                "strategy": pos.strategy,
                "direction": pos.direction,
                "entry_price": round(pos.entry_price, 2),
                "stop_loss": round(pos.stop_price, 2),
                "take_profit": round(pos.tp_price, 2),
                "size": pos.size,
                "entry_time": pos.entry_time,
            },
        }
    else:
        return {
            "status": "FAILED",
            "reason": "Order created but position not filled — check sizing/equity",
            "order_id": order.order_id,
        }


def close_test_trade(order_id: str = "", close_price: float = 0.0) -> dict:
    """
    Close a test trade manually.
    If order_id not specified, closes the first TEST_ position found.
    """
    engine = get_execution_engine()

    # Find test position
    test_pos = None
    for pos in engine.open_positions:
        if pos.strategy.startswith("TEST_"):
            if not order_id or pos.order_id == order_id:
                test_pos = pos
                break

    if not test_pos:
        return {"status": "NOT_FOUND", "reason": "No open test position found"}

    # Get close price
    if close_price <= 0:
        try:
            from bahamut.execution.v7_orchestrator import _fetch_candles
            candles = _fetch_candles(test_pos.asset, count=5)
            if candles:
                close_price = float(candles[-1].get("close", 0))
        except Exception:
            pass
        if close_price <= 0:
            close_price = test_pos.entry_price * 1.01  # +1% for test

    # Force close
    trade = engine.broker.force_close(test_pos, close_price, "TEST_MANUAL_CLOSE")
    engine.open_positions.remove(test_pos)
    engine.closed_trades.append(trade)

    logger.info("test_trade_closed",
                 order_id=test_pos.order_id, pnl=trade.pnl,
                 exit_reason="TEST_MANUAL_CLOSE")

    return {
        "status": "CLOSED",
        "trade": {
            "order_id": trade.order_id,
            "asset": trade.asset,
            "strategy": trade.strategy,
            "direction": trade.direction,
            "entry_price": round(trade.entry_price, 2),
            "exit_price": round(trade.exit_price, 2),
            "pnl": round(trade.pnl, 2),
            "pnl_pct": round(trade.pnl_pct * 100, 2),
            "exit_reason": trade.exit_reason,
            "bars_held": trade.bars_held,
        },
    }


def get_test_trade_status() -> dict:
    """Get current test trade state."""
    engine = get_execution_engine()
    test_positions = [p for p in engine.open_positions if p.strategy.startswith("TEST_")]
    test_trades = [t for t in engine.closed_trades if t.strategy.startswith("TEST_")]

    return {
        "open_test_positions": len(test_positions),
        "closed_test_trades": len(test_trades),
        "positions": [
            {
                "order_id": p.order_id, "asset": p.asset, "strategy": p.strategy,
                "direction": p.direction, "entry_price": round(p.entry_price, 2),
                "current_price": round(p.current_price, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "bars_held": p.bars_held,
            }
            for p in test_positions
        ],
        "trades": [
            {
                "order_id": t.order_id, "asset": t.asset, "strategy": t.strategy,
                "pnl": round(t.pnl, 2), "exit_reason": t.exit_reason,
            }
            for t in test_trades
        ],
    }
