"""
v7 DB Persistence — sync execution engine state to PostgreSQL.

Called periodically to persist in-memory state.
"""
import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from bahamut.database import sync_engine

logger = structlog.get_logger()


def persist_trade(trade: dict):
    """Save a closed trade to DB."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO v7_trades (trade_id, order_id, strategy_name, asset, direction,
                    entry_price, exit_price, stop_price, tp_price, size, risk_amount,
                    pnl, pnl_pct, entry_time, exit_time, exit_reason, bars_held)
                VALUES (:tid, :oid, :strat, :asset, :dir, :entry, :exit, :sl, :tp,
                    :size, :risk, :pnl, :pnl_pct, :entry_t, :exit_t, :reason, :bars)
                ON CONFLICT (trade_id) DO NOTHING
            """), {
                "tid": trade.get("trade_id", ""),
                "oid": trade.get("order_id", ""),
                "strat": trade.get("strategy", ""),
                "asset": trade.get("asset", ""),
                "dir": trade.get("direction", ""),
                "entry": trade.get("entry_price", 0),
                "exit": trade.get("exit_price", 0),
                "sl": trade.get("stop_price", 0),
                "tp": trade.get("tp_price", 0),
                "size": trade.get("size", 0),
                "risk": trade.get("risk_amount", 0),
                "pnl": trade.get("pnl", 0),
                "pnl_pct": trade.get("pnl_pct", 0),
                "entry_t": trade.get("entry_time"),
                "exit_t": trade.get("exit_time"),
                "reason": trade.get("exit_reason", ""),
                "bars": trade.get("bars_held", 0),
            })
            conn.commit()
    except Exception as e:
        logger.error("persist_trade_failed", error=str(e))


def persist_order(order: dict):
    """Save/update an order to DB."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO v7_orders (order_id, strategy_name, asset, direction, status,
                    signal_time, fill_time, entry_price, stop_price, tp_price,
                    size, risk_amount, sl_pct, tp_pct, max_hold_bars, signal_id)
                VALUES (:oid, :strat, :asset, :dir, :status, :sig_t, :fill_t,
                    :entry, :sl, :tp, :size, :risk, :sl_pct, :tp_pct, :hold, :sig_id)
                ON CONFLICT (order_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    fill_time = EXCLUDED.fill_time,
                    entry_price = EXCLUDED.entry_price,
                    stop_price = EXCLUDED.stop_price,
                    tp_price = EXCLUDED.tp_price,
                    size = EXCLUDED.size,
                    risk_amount = EXCLUDED.risk_amount
            """), {
                "oid": order.get("order_id", ""),
                "strat": order.get("strategy", ""),
                "asset": order.get("asset", ""),
                "dir": order.get("direction", ""),
                "status": order.get("status", "PENDING"),
                "sig_t": order.get("signal_time"),
                "fill_t": order.get("fill_time"),
                "entry": order.get("entry_price", 0),
                "sl": order.get("stop_price", 0),
                "tp": order.get("tp_price", 0),
                "size": order.get("size", 0),
                "risk": order.get("risk_amount", 0),
                "sl_pct": order.get("sl_pct", 0),
                "tp_pct": order.get("tp_pct", 0),
                "hold": order.get("max_hold_bars", 30),
                "sig_id": order.get("signal_id", ""),
            })
            conn.commit()
    except Exception as e:
        logger.error("persist_order_failed", error=str(e))


def persist_sleeve(name: str, data: dict):
    """Update sleeve state in DB."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                UPDATE strategy_sleeves SET
                    allocation_weight = :weight,
                    allocated_capital = :alloc,
                    current_equity = :equity,
                    realized_pnl = :rpnl,
                    unrealized_pnl = :upnl,
                    peak_equity = :peak,
                    drawdown = :dd,
                    trade_count = :trades,
                    win_count = :wins,
                    enabled = :enabled,
                    updated_at = NOW()
                WHERE strategy_name = :name
            """), {
                "name": name,
                "weight": data.get("weight", 0.5),
                "alloc": data.get("initial_capital", 50000),
                "equity": data.get("equity", 50000),
                "rpnl": data.get("realized_pnl", 0),
                "upnl": data.get("unrealized_pnl", 0),
                "peak": data.get("peak_equity", 50000),
                "dd": data.get("drawdown", 0),
                "trades": data.get("trades", 0),
                "wins": data.get("wins", 0),
                "enabled": data.get("enabled", True),
            })
            conn.commit()
    except Exception as e:
        logger.error("persist_sleeve_failed", error=str(e))


def persist_snapshot(snapshot: dict):
    """Save portfolio snapshot."""
    try:
        import json
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO v7_portfolio_snapshots
                    (timestamp, total_equity, total_realized_pnl, total_unrealized_pnl,
                     total_open_risk, drawdown, sleeve_data)
                VALUES (:ts, :eq, :rpnl, :upnl, :risk, :dd, :sleeves::jsonb)
            """), {
                "ts": snapshot.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "eq": snapshot.get("total_equity", 0),
                "rpnl": snapshot.get("total_realized_pnl", 0),
                "upnl": snapshot.get("total_unrealized_pnl", 0),
                "risk": snapshot.get("total_open_risk", 0),
                "dd": snapshot.get("drawdown", 0),
                "sleeves": json.dumps(snapshot.get("sleeve_data", {})),
            })
            conn.commit()
    except Exception as e:
        logger.error("persist_snapshot_failed", error=str(e))


def load_trades_from_db() -> list[dict]:
    """Load historical trades from DB."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM v7_trades ORDER BY exit_time DESC LIMIT 200"
            )).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []


def load_snapshots_from_db(limit: int = 500) -> list[dict]:
    """Load equity curve snapshots from DB."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM v7_portfolio_snapshots ORDER BY timestamp DESC LIMIT :n"
            ), {"n": limit}).mappings().all()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []
