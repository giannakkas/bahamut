"""
Bahamut Test Trade Mode

Allows operator to create a synthetic paper trade to verify the full lifecycle:
  signal -> order -> position -> close -> performance update

CROSS-PROCESS:
  Backend runs --workers 2. Test trade created in worker A must be
  visible to worker B when dashboard polls.
  Solution: persist test positions to Redis (fast, cross-process) + DB (durable).
"""
import json
import os
import structlog
from datetime import datetime, timezone

from bahamut.execution.engine import get_execution_engine
from bahamut.execution.models import ClosedTrade
from bahamut.portfolio.manager import get_portfolio_manager
from bahamut.strategies.base import Signal

logger = structlog.get_logger()


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _save_test_position_to_redis(order_id: str, data: dict):
    r = _get_redis()
    if r:
        try:
            r.hset("bahamut:test_positions", order_id, json.dumps(data))
        except Exception:
            pass


def _remove_test_position_from_redis(order_id: str):
    r = _get_redis()
    if r:
        try:
            r.hdel("bahamut:test_positions", order_id)
        except Exception:
            pass


def _save_test_trade_to_redis(data: dict):
    r = _get_redis()
    if r:
        try:
            r.lpush("bahamut:test_trades", json.dumps(data))
            r.ltrim("bahamut:test_trades", 0, 49)
        except Exception:
            pass


def get_test_positions_from_redis() -> list[dict]:
    """Read open test positions from Redis (cross-process)."""
    r = _get_redis()
    if not r:
        return []
    try:
        raw = r.hgetall("bahamut:test_positions")
        return [json.loads(v) for v in raw.values()]
    except Exception:
        return []


def get_test_trades_from_redis() -> list[dict]:
    """Read closed test trades from Redis (cross-process)."""
    r = _get_redis()
    if not r:
        return []
    try:
        raw = r.lrange("bahamut:test_trades", 0, 49)
        return [json.loads(x) for x in raw]
    except Exception:
        return []


def create_test_trade(
    asset: str = "BTCUSD",
    strategy: str = "test_trade",
    direction: str = "LONG",
    entry_price: float = 0.0,
) -> dict:
    engine = get_execution_engine()
    pm = get_portfolio_manager()

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

    signal = Signal(
        strategy=f"TEST_{strategy}", asset=asset, direction=direction,
        sl_pct=0.03, tp_pct=0.06, max_hold_bars=10,
        quality=1.0, reason="TEST TRADE - operator verification",
    )

    order = engine.submit_signal(signal, pm.total_equity)
    if not order:
        return {"status": "REJECTED", "reason": "Signal rejected - kill switch active or duplicate"}

    bar = {
        "open": entry_price, "high": entry_price * 1.001,
        "low": entry_price * 0.999, "close": entry_price,
        "datetime": datetime.now(timezone.utc).isoformat(),
    }
    engine.on_new_bar(bar, {f"TEST_{strategy}": pm.total_equity * 0.1}, asset=asset)

    test_positions = [p for p in engine.open_positions if p.strategy == f"TEST_{strategy}"]

    if test_positions:
        pos = test_positions[0]
        logger.info("test_trade_opened", asset=asset, entry=pos.entry_price)

        # Persist to Redis for cross-process visibility
        pos_data = {
            "order_id": pos.order_id, "asset": pos.asset,
            "strategy": pos.strategy, "direction": pos.direction,
            "entry_price": round(pos.entry_price, 2),
            "current_price": round(pos.current_price, 2),
            "stop_loss": round(pos.stop_price, 2),
            "take_profit": round(pos.tp_price, 2),
            "size": pos.size, "risk_amount": round(pos.risk_amount, 2),
            "unrealized_pnl": 0, "bars_held": 0,
            "entry_time": pos.entry_time,
        }
        _save_test_position_to_redis(pos.order_id, pos_data)

        # Persist order to DB
        try:
            from bahamut.execution.v7_persistence import persist_order
            persist_order({
                "order_id": order.order_id, "strategy": order.strategy,
                "asset": order.asset, "direction": order.direction,
                "status": "OPEN", "signal_time": order.signal_time,
                "fill_time": order.fill_time, "entry_price": pos.entry_price,
                "stop_price": pos.stop_price, "tp_price": pos.tp_price,
                "size": pos.size, "risk_amount": pos.risk_amount,
                "sl_pct": order.sl_pct, "tp_pct": order.tp_pct,
                "max_hold_bars": order.max_hold_bars, "signal_id": order.signal_id,
            })
        except Exception as e:
            logger.warning("test_trade_db_persist_failed", error=str(e))

        try:
            from bahamut.monitoring.trade_audit import log_trade_event
            log_trade_event("test_trade.opened",
                f"TEST {direction} {asset} @ ${pos.entry_price:,.2f}", actor="operator")
        except Exception:
            pass

        return {
            "status": "OPENED", "order_id": order.order_id,
            "position": {
                "asset": pos.asset, "strategy": pos.strategy,
                "direction": pos.direction,
                "entry_price": round(pos.entry_price, 2),
                "stop_loss": round(pos.stop_price, 2),
                "take_profit": round(pos.tp_price, 2),
                "size": pos.size, "entry_time": pos.entry_time,
            },
        }
    return {
        "status": "FAILED",
        "reason": "Order created but position not filled",
        "order_id": order.order_id,
    }


def close_test_trade(order_id: str = "", close_price: float = 0.0) -> dict:
    engine = get_execution_engine()

    # Check in-memory engine first
    test_pos = None
    for pos in engine.open_positions:
        if pos.strategy.startswith("TEST_"):
            if not order_id or pos.order_id == order_id:
                test_pos = pos
                break

    # If not in this process, check Redis (cross-process)
    if not test_pos:
        redis_positions = get_test_positions_from_redis()
        if redis_positions:
            target = redis_positions[0]
            if order_id:
                target = next((p for p in redis_positions if p["order_id"] == order_id), redis_positions[0])

            _remove_test_position_from_redis(target["order_id"])

            ep = target.get("entry_price", 0)
            if close_price <= 0:
                try:
                    from bahamut.execution.v7_orchestrator import _fetch_candles
                    candles = _fetch_candles(target.get("asset", "BTCUSD"), count=5)
                    if candles:
                        close_price = float(candles[-1].get("close", 0))
                except Exception:
                    pass
                if close_price <= 0:
                    close_price = ep * 1.01

            d = target.get("direction", "LONG")
            sz = target.get("size", 0)
            pnl = (close_price - ep) * sz if d == "LONG" else (ep - close_price) * sz

            trade_data = {
                "order_id": target["order_id"], "asset": target.get("asset", ""),
                "strategy": target.get("strategy", ""), "direction": d,
                "entry_price": round(ep, 2), "exit_price": round(close_price, 2),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl / max(1, ep * sz) * 100, 2) if sz > 0 else 0,
                "exit_reason": "TEST_MANUAL_CLOSE", "bars_held": 0,
            }
            _save_test_trade_to_redis(trade_data)

            try:
                import uuid
                from bahamut.execution.v7_persistence import persist_trade
                persist_trade({"trade_id": str(uuid.uuid4())[:12], **trade_data,
                    "stop_price": target.get("stop_loss", 0), "tp_price": target.get("take_profit", 0),
                    "size": sz, "risk_amount": target.get("risk_amount", 0),
                    "entry_time": target.get("entry_time", ""),
                    "exit_time": datetime.now(timezone.utc).isoformat()})
            except Exception as e:
                logger.warning("test_trade_db_close_failed", error=str(e))

            logger.info("test_trade_closed_cross_process", order_id=target["order_id"], pnl=round(pnl, 2))
            return {"status": "CLOSED", "trade": trade_data}

    if not test_pos:
        return {"status": "NOT_FOUND", "reason": "No open test position found"}

    if close_price <= 0:
        try:
            from bahamut.execution.v7_orchestrator import _fetch_candles
            candles = _fetch_candles(test_pos.asset, count=5)
            if candles:
                close_price = float(candles[-1].get("close", 0))
        except Exception:
            pass
        if close_price <= 0:
            close_price = test_pos.entry_price * 1.01

    trade = engine.broker.force_close(test_pos, close_price, "TEST_MANUAL_CLOSE")
    engine.open_positions.remove(test_pos)
    engine.closed_trades.append(trade)
    _remove_test_position_from_redis(test_pos.order_id)

    trade_data = {
        "order_id": trade.order_id, "asset": trade.asset,
        "strategy": trade.strategy, "direction": trade.direction,
        "entry_price": round(trade.entry_price, 2), "exit_price": round(trade.exit_price, 2),
        "pnl": round(trade.pnl, 2), "pnl_pct": round(trade.pnl_pct * 100, 2),
        "exit_reason": trade.exit_reason, "bars_held": trade.bars_held,
    }
    _save_test_trade_to_redis(trade_data)

    try:
        from bahamut.execution.v7_persistence import persist_trade
        persist_trade({
            "trade_id": trade.trade_id, "order_id": trade.order_id,
            "strategy": trade.strategy, "asset": trade.asset,
            "direction": trade.direction, "entry_price": trade.entry_price,
            "exit_price": trade.exit_price, "stop_price": trade.stop_price,
            "tp_price": trade.tp_price, "size": trade.size,
            "risk_amount": trade.risk_amount, "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct, "entry_time": trade.entry_time,
            "exit_time": trade.exit_time, "exit_reason": trade.exit_reason,
            "bars_held": trade.bars_held,
        })
    except Exception as e:
        logger.warning("test_trade_db_close_failed", error=str(e))

    logger.info("test_trade_closed", order_id=test_pos.order_id, pnl=trade.pnl)

    try:
        from bahamut.monitoring.trade_audit import log_trade_event
        log_trade_event("test_trade.closed",
            f"TEST {trade.asset} closed @ ${trade.exit_price:,.2f}, PnL ${trade.pnl:,.2f}",
            actor="operator")
    except Exception:
        pass

    return {"status": "CLOSED", "trade": trade_data}


def get_test_trade_status() -> dict:
    """Merges in-memory + Redis for cross-process visibility."""
    engine = get_execution_engine()

    mem_positions = [p for p in engine.open_positions if p.strategy.startswith("TEST_")]
    mem_trades = [t for t in engine.closed_trades if t.strategy.startswith("TEST_")]

    redis_positions = get_test_positions_from_redis()
    redis_trades = get_test_trades_from_redis()

    mem_ids = {p.order_id for p in mem_positions}
    all_positions = [
        {"order_id": p.order_id, "asset": p.asset, "strategy": p.strategy,
         "direction": p.direction, "entry_price": round(p.entry_price, 2),
         "current_price": round(p.current_price, 2),
         "unrealized_pnl": round(p.unrealized_pnl, 2), "bars_held": p.bars_held}
        for p in mem_positions
    ]
    for rp in redis_positions:
        if rp.get("order_id") not in mem_ids:
            all_positions.append(rp)

    mem_tids = {t.order_id for t in mem_trades}
    all_trades = [
        {"order_id": t.order_id, "asset": t.asset, "strategy": t.strategy,
         "pnl": round(t.pnl, 2), "exit_reason": t.exit_reason}
        for t in mem_trades
    ]
    for rt in redis_trades:
        if rt.get("order_id") not in mem_tids:
            all_trades.append(rt)

    return {
        "open_test_positions": len(all_positions),
        "closed_test_trades": len(all_trades),
        "positions": all_positions,
        "trades": all_trades,
    }
