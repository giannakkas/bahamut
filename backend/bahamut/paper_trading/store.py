"""
Bahamut.AI — Paper Trading Store (Canonical Writer)

ALL writes to paper_portfolios and paper_positions MUST go through this module.
Other modules call these functions instead of writing directly.
Reads can happen from anywhere.
"""
import json
import structlog
from sqlalchemy import text
from bahamut.db.query import get_connection

logger = structlog.get_logger()


# ─── Portfolio Operations ───

def get_or_create_portfolio(name: str = "SYSTEM_DEMO", balance: float = 100000.0) -> dict | None:
    """Get existing portfolio or create a new one. Returns dict with id, balance, etc."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct "
            "FROM paper_portfolios WHERE name = :n"
        ), {"n": name}).mappings().first()
        if row:
            return dict(row)

        conn.execute(text(
            "INSERT INTO paper_portfolios (name, initial_balance, current_balance, peak_balance) "
            "VALUES (:n, :b, :b, :b)"
        ), {"n": name, "b": balance})
        conn.commit()
        row = conn.execute(text(
            "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct "
            "FROM paper_portfolios WHERE name = :n"
        ), {"n": name}).mappings().first()
        return dict(row) if row else None


def update_portfolio_after_close(portfolio_id: int, pnl: float) -> None:
    """Update portfolio balance and stats after closing a position."""
    with get_connection() as conn:
        conn.execute(text("""
            UPDATE paper_portfolios
            SET current_balance = current_balance + :pnl,
                total_pnl = total_pnl + :pnl,
                total_trades = total_trades + 1,
                winning_trades = winning_trades + CASE WHEN :pnl > 0 THEN 1 ELSE 0 END,
                losing_trades = losing_trades + CASE WHEN :pnl <= 0 THEN 1 ELSE 0 END,
                updated_at = NOW()
            WHERE id = :pid
        """), {"pnl": round(pnl, 2), "pid": portfolio_id})
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
                  agent_votes: dict, cycle_id: str = None,
                  trading_profile: str = None, regime: str = None,
                  disagreement_index: float = None, execution_mode: str = None) -> int | None:
    """Insert a new OPEN position. Returns position ID or None on failure."""
    sql = """
        INSERT INTO paper_positions (
            portfolio_id, asset, direction, entry_price, quantity, position_value,
            entry_signal_score, entry_signal_label, stop_loss, take_profit,
            risk_amount, atr_at_entry, current_price, consensus_score, agent_votes,
            cycle_id, status, opened_at
        ) VALUES (
            :pid, :asset, :dir, :ep, :qty, :pv,
            :ess, :esl, :sl, :tp,
            :ra, :atr, :ep, :cs, CAST(:av AS jsonb),
            :cid, 'OPEN', NOW()
        )
    """
    params = {
        "pid": portfolio_id, "asset": asset, "dir": direction,
        "ep": entry_price, "qty": round(quantity, 6), "pv": round(position_value, 2),
        "ess": entry_signal_score, "esl": entry_signal_label,
        "sl": round(stop_loss, 6), "tp": round(take_profit, 6),
        "ra": round(risk_amount, 2), "atr": atr_at_entry,
        "cs": consensus_score, "av": json.dumps(agent_votes),
        "cid": cycle_id,
    }
    try:
        with get_connection() as conn:
            conn.execute(text(sql), params)
            conn.commit()
            row = conn.execute(text(
                "SELECT id FROM paper_positions WHERE cycle_id = :c ORDER BY opened_at DESC LIMIT 1"
            ), {"c": cycle_id}).fetchone()
            pos_id = row[0] if row else None

        logger.info("position_opened", asset=asset, direction=direction,
                     position_id=pos_id, cycle_id=cycle_id)
        return pos_id
    except Exception as e:
        logger.error("open_position_failed", asset=asset, error=str(e))
        return None


def close_position(position_id: int, exit_price: float, realized_pnl: float,
                   realized_pnl_pct: float, status: str = "CLOSED",
                   update_portfolio: bool = True) -> None:
    """Close a position with exit details. Optionally updates portfolio stats."""
    with get_connection() as conn:
        # Get portfolio_id before closing
        portfolio_id = None
        if update_portfolio:
            row = conn.execute(text(
                "SELECT portfolio_id FROM paper_positions WHERE id = :pid"
            ), {"pid": position_id}).fetchone()
            portfolio_id = row[0] if row else None

        conn.execute(text("""
            UPDATE paper_positions SET
                status = :status, exit_price = :ep, realized_pnl = :rpnl,
                realized_pnl_pct = :rpct, closed_at = NOW()
            WHERE id = :pid AND status = 'OPEN'
        """), {
            "pid": position_id, "status": status,
            "ep": exit_price, "rpnl": round(realized_pnl, 2),
            "rpct": round(realized_pnl_pct, 2),
        })
        conn.commit()

    if update_portfolio and portfolio_id:
        update_portfolio_after_close(portfolio_id, realized_pnl)

    logger.info("position_closed", position_id=position_id, status=status,
                exit_price=exit_price, realized_pnl=realized_pnl)


def close_position_for_reallocation(position_id: int) -> dict | None:
    """Close a position for reallocation. Returns position details for logging, or None."""
    with get_connection() as conn:
        row = conn.execute(text("""
            SELECT id, asset, direction, entry_price, current_price, quantity,
                   position_value, portfolio_id
            FROM paper_positions WHERE id = :pid AND status = 'OPEN'
        """), {"pid": position_id}).mappings().first()

        if not row:
            return None

        current = float(row["current_price"] or row["entry_price"])
        entry = float(row["entry_price"])
        qty = float(row["quantity"])
        direction = row["direction"]
        pnl = (current - entry) * qty if direction == "LONG" else (entry - current) * qty
        pnl_pct = (pnl / float(row["position_value"])) * 100 if row["position_value"] else 0

        conn.execute(text("""
            UPDATE paper_positions
            SET status = 'CLOSED_REALLOC', exit_price = :price, realized_pnl = :pnl,
                realized_pnl_pct = :pnl_pct, closed_at = NOW()
            WHERE id = :pid
        """), {"price": current, "pnl": round(pnl, 2),
               "pnl_pct": round(pnl_pct, 2), "pid": position_id})

        conn.execute(text("""
            UPDATE paper_portfolios
            SET current_balance = current_balance + :pnl,
                total_pnl = total_pnl + :pnl,
                total_trades = total_trades + 1,
                winning_trades = winning_trades + CASE WHEN :pnl > 0 THEN 1 ELSE 0 END,
                losing_trades = losing_trades + CASE WHEN :pnl <= 0 THEN 1 ELSE 0 END
            WHERE id = :portfolio_id
        """), {"pnl": round(pnl, 2), "portfolio_id": row["portfolio_id"]})

        conn.commit()

    logger.info("position_closed_realloc", position_id=position_id,
                asset=row["asset"], pnl=round(pnl, 2))
    return {"position_id": position_id, "asset": row["asset"],
            "direction": direction, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}


def close_all_positions() -> int:
    """Emergency kill switch — close ALL open positions. Returns count closed."""
    with get_connection() as conn:
        r = conn.execute(text("""
            UPDATE paper_positions SET status='CLOSED_MANUAL', closed_at=NOW(),
            exit_price=current_price,
            realized_pnl=CASE WHEN direction='LONG' THEN (current_price-entry_price)*quantity
            ELSE (entry_price-current_price)*quantity END
            WHERE status='OPEN' RETURNING id
        """))
        closed = r.rowcount
        conn.commit()
    logger.warning("kill_switch_all_closed", positions_closed=closed)
    return closed


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


def get_position_by_id(position_id: int) -> dict | None:
    """Get a single position by ID."""
    from bahamut.db.query import run_query_one
    return run_query_one(
        "SELECT * FROM paper_positions WHERE id = :pid",
        {"pid": position_id}
    )


def get_position_id_by_cycle(cycle_id: str) -> int | None:
    """Get position ID by cycle_id."""
    with get_connection() as conn:
        row = conn.execute(text(
            "SELECT id FROM paper_positions WHERE cycle_id = :c ORDER BY opened_at DESC LIMIT 1"
        ), {"c": cycle_id}).fetchone()
        return row[0] if row else None
