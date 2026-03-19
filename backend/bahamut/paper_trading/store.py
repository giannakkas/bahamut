"""
Bahamut.AI — Paper Trading Store (Canonical Writer)

ALL writes to paper_portfolios and paper_positions MUST go through this module.
Other modules (allocator, execution router) call these functions instead of
writing directly.

Reads can happen from anywhere (no exclusive read ownership).
"""
import structlog
from sqlalchemy import text
from bahamut.db.query import get_connection

logger = structlog.get_logger()


# ─── Portfolio Operations ───

def get_or_create_portfolio(name: str = "SYSTEM_DEMO", balance: float = 100000.0) -> dict:
    """Get existing portfolio or create a new one. Returns dict with id, balance."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT id, current_balance FROM paper_portfolios WHERE name = :n"
        ), {"n": name}).fetchone()
        if row:
            return {"id": row[0], "current_balance": row[1]}

        conn.execute(text(
            "INSERT INTO paper_portfolios (name, initial_balance, current_balance, peak_balance) "
            "VALUES (:n, :b, :b, :b)"
        ), {"n": name, "b": balance})
        conn.commit()
        row = conn.execute(text(
            "SELECT id, current_balance FROM paper_portfolios WHERE name = :n"
        ), {"n": name}).fetchone()
        return {"id": row[0], "current_balance": row[1]}


def update_portfolio_balance(portfolio_id: int, new_balance: float,
                             total_pnl: float = None, total_pnl_pct: float = None,
                             total_trades: int = None, winning_trades: int = None,
                             losing_trades: int = None, win_rate: float = None,
                             best_trade_pnl: float = None, worst_trade_pnl: float = None,
                             max_drawdown: float = None, peak_balance: float = None) -> None:
    """Update portfolio balance and stats after trade close."""
    updates = ["current_balance = :bal", "updated_at = NOW()"]
    params = {"pid": portfolio_id, "bal": new_balance}

    optionals = {
        "total_pnl": total_pnl, "total_pnl_pct": total_pnl_pct,
        "total_trades": total_trades, "winning_trades": winning_trades,
        "losing_trades": losing_trades, "win_rate": win_rate,
        "best_trade_pnl": best_trade_pnl, "worst_trade_pnl": worst_trade_pnl,
        "max_drawdown": max_drawdown, "peak_balance": peak_balance,
    }
    for k, v in optionals.items():
        if v is not None:
            updates.append(f"{k} = :{k}")
            params[k] = v

    sql = f"UPDATE paper_portfolios SET {', '.join(updates)} WHERE id = :pid"
    with get_connection() as conn:
        conn.execute(text(sql), params)
        conn.commit()


def get_portfolio_balance(portfolio_id: int) -> float:
    """Get current balance for a portfolio."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT current_balance FROM paper_portfolios WHERE id = :p"
        ), {"p": portfolio_id}).fetchone()
        return row[0] if row else 0.0


# ─── Position Operations ───

def open_position(portfolio_id: int, asset: str, direction: str, entry_price: float,
                  quantity: float, position_value: float, entry_signal_score: float,
                  entry_signal_label: str, stop_loss: float, take_profit: float,
                  risk_amount: float, atr_at_entry: float, consensus_score: float,
                  agent_votes: dict, cycle_id: str = None) -> int | None:
    """Insert a new OPEN position. Returns position ID or None on failure."""
    import json
    sql = """
        INSERT INTO paper_positions (
            portfolio_id, asset, direction, entry_price, quantity, position_value,
            entry_signal_score, entry_signal_label, stop_loss, take_profit,
            risk_amount, atr_at_entry, current_price, consensus_score, agent_votes,
            cycle_id, status
        ) VALUES (
            :pid, :asset, :dir, :ep, :qty, :pv,
            :ess, :esl, :sl, :tp,
            :ra, :atr, :ep, :cs, :av,
            :cid, 'OPEN'
        )
    """
    params = {
        "pid": portfolio_id, "asset": asset, "dir": direction,
        "ep": entry_price, "qty": quantity, "pv": position_value,
        "ess": entry_signal_score, "esl": entry_signal_label,
        "sl": stop_loss, "tp": take_profit, "ra": risk_amount,
        "atr": atr_at_entry, "cs": consensus_score,
        "av": json.dumps(agent_votes), "cid": cycle_id,
    }
    try:
        with get_connection() as conn:
            conn.execute(text(sql), params)
            conn.commit()
            # Get the inserted ID
            row = conn.execute(text(
                "SELECT id FROM paper_positions WHERE cycle_id = :c ORDER BY opened_at DESC LIMIT 1"
            ), {"c": cycle_id}).fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error("open_position_failed", asset=asset, error=str(e))
        return None


def close_position(position_id: int, exit_price: float, realized_pnl: float,
                   realized_pnl_pct: float, status: str = "CLOSED") -> None:
    """Close a position with exit details."""
    sql = """
        UPDATE paper_positions SET
            status = :status, exit_price = :ep, realized_pnl = :rpnl,
            realized_pnl_pct = :rpct, closed_at = NOW()
        WHERE id = :pid AND status = 'OPEN'
    """
    with get_connection() as conn:
        conn.execute(text(sql), {
            "pid": position_id, "status": status,
            "ep": exit_price, "rpnl": realized_pnl, "rpct": realized_pnl_pct,
        })
        conn.commit()
    logger.info("position_closed", position_id=position_id, status=status,
                exit_price=exit_price, realized_pnl=realized_pnl)


def close_position_manual(position_id: int, exit_price: float,
                          realized_pnl: float, realized_pnl_pct: float) -> None:
    """Manually close a position (from execution router)."""
    close_position(position_id, exit_price, realized_pnl, realized_pnl_pct,
                   status="CLOSED_MANUAL")


def update_position_price(position_id: int, current_price: float,
                          unrealized_pnl: float, unrealized_pnl_pct: float,
                          max_favorable: float = None, max_adverse: float = None) -> None:
    """Update live price data on an open position."""
    updates = ["current_price = :cp", "unrealized_pnl = :up", "unrealized_pnl_pct = :upct"]
    params = {"pid": position_id, "cp": current_price, "up": unrealized_pnl, "upct": unrealized_pnl_pct}
    if max_favorable is not None:
        updates.append("max_favorable = GREATEST(max_favorable, :mf)")
        params["mf"] = max_favorable
    if max_adverse is not None:
        updates.append("max_adverse = GREATEST(max_adverse, :ma)")
        params["ma"] = max_adverse

    sql = f"UPDATE paper_positions SET {', '.join(updates)} WHERE id = :pid"
    with get_connection() as conn:
        conn.execute(text(sql), params)
        conn.commit()


def get_open_positions(portfolio_id: int) -> list[dict]:
    """Get all open positions for a portfolio."""
    from bahamut.db.query import run_query
    return run_query(
        "SELECT * FROM paper_positions WHERE portfolio_id = :p AND status = 'OPEN'",
        {"p": portfolio_id}
    )


def get_open_position_count(portfolio_id: int) -> int:
    """Get count of open positions."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM paper_positions WHERE portfolio_id = :p AND status = 'OPEN'"
        ), {"p": portfolio_id}).fetchone()
        return row[0] if row else 0


def has_open_position(portfolio_id: int, asset: str) -> bool:
    """Check if there's an existing open position for this asset."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT id FROM paper_positions WHERE portfolio_id = :p AND asset = :a AND status = 'OPEN'"
        ), {"p": portfolio_id, "a": asset}).fetchone()
        return row is not None
