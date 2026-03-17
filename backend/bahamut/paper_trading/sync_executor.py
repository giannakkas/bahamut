"""
Sync Paper Trading Executor — for Celery workers.
Uses sync SQLAlchemy/raw SQL to avoid async event loop issues.
"""

import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from bahamut.database import sync_engine

logger = structlog.get_logger(__name__)


def process_signal_sync(
    asset: str,
    direction: str,
    consensus_score: float,
    signal_label: str,
    entry_price: float,
    atr: float,
    agent_votes: dict,
    cycle_id: str = None,
) -> dict:
    """Sync version of process_signal for Celery workers."""
    import json

    log = logger.bind(asset=asset, direction=direction, score=consensus_score)

    # Gate: only trade SIGNAL or STRONG_SIGNAL
    if signal_label not in ("STRONG_SIGNAL", "SIGNAL"):
        log.info("paper_trade_skipped_sync", reason="weak_signal", label=signal_label)
        return {"action": "SKIP", "reason": f"Only trading SIGNAL or STRONG_SIGNAL, got {signal_label}"}

    if consensus_score < 0.45:
        log.info("paper_trade_skipped_sync", reason="score_too_low")
        return {"action": "SKIP", "reason": "Score below 0.45"}

    if entry_price <= 0:
        return {"action": "SKIP", "reason": "Invalid price"}

    try:
        with sync_engine.connect() as conn:
            # Get or create portfolio
            result = conn.execute(text(
                "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
            ))
            portfolio = result.mappings().first()

            if not portfolio:
                conn.execute(text(
                    "INSERT INTO paper_portfolios (name, initial_balance, current_balance, peak_balance) VALUES ('SYSTEM_DEMO', 100000, 100000, 100000)"
                ))
                conn.commit()
                result = conn.execute(text(
                    "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
                ))
                portfolio = result.mappings().first()

            if not portfolio or not portfolio["is_active"]:
                return {"action": "SKIP", "reason": "Portfolio inactive"}

            portfolio_id = portfolio["id"]
            balance = portfolio["current_balance"]
            max_positions = portfolio["max_open_positions"] or 5
            risk_pct = portfolio["risk_per_trade_pct"] or 2.0

            # Check open positions count
            result = conn.execute(text(
                "SELECT COUNT(*) as cnt FROM paper_positions WHERE portfolio_id = :pid AND status = 'OPEN'"
            ), {"pid": portfolio_id})
            open_count = result.scalar()

            if open_count >= max_positions:
                log.info("paper_trade_skipped_sync", reason="max_positions", open=open_count)
                return {"action": "SKIP", "reason": f"Max positions ({open_count}/{max_positions})"}

            # Check duplicate
            result = conn.execute(text(
                "SELECT id FROM paper_positions WHERE portfolio_id = :pid AND asset = :asset AND status = 'OPEN'"
            ), {"pid": portfolio_id, "asset": asset})
            if result.first():
                log.info("paper_trade_skipped_sync", reason="duplicate_asset")
                return {"action": "SKIP", "reason": f"Already in {asset}"}

            # Calculate SL/TP
            if atr <= 0:
                atr = entry_price * 0.01

            sl_distance = atr * 2.0
            tp_distance = atr * 3.0

            if direction == "LONG":
                stop_loss = entry_price - sl_distance
                take_profit = entry_price + tp_distance
            else:
                stop_loss = entry_price + sl_distance
                take_profit = entry_price - tp_distance

            # Position sizing
            risk_amount = balance * (risk_pct / 100.0)
            quantity = risk_amount / sl_distance if sl_distance > 0 else 1
            position_value = quantity * entry_price

            # Insert position
            conn.execute(text("""
                INSERT INTO paper_positions (
                    portfolio_id, asset, direction, entry_price, quantity, position_value,
                    entry_signal_score, entry_signal_label, stop_loss, take_profit,
                    risk_amount, atr_at_entry, current_price, agent_votes, consensus_score,
                    cycle_id, status, opened_at
                ) VALUES (
                    :pid, :asset, :dir, :price, :qty, :val,
                    :score, :label, :sl, :tp,
                    :risk, :atr, :price, :votes, :cscore,
                    :cid, 'OPEN', NOW()
                )
            """), {
                "pid": portfolio_id,
                "asset": asset,
                "dir": direction,
                "price": entry_price,
                "qty": round(quantity, 6),
                "val": round(position_value, 2),
                "score": consensus_score,
                "label": signal_label,
                "sl": round(stop_loss, 6),
                "tp": round(take_profit, 6),
                "risk": round(risk_amount, 2),
                "atr": atr,
                "votes": json.dumps(agent_votes),
                "cscore": consensus_score,
                "cid": cycle_id,
            })
            conn.commit()

            log.info("paper_trade_opened_sync",
                     asset=asset, direction=direction,
                     entry=entry_price, sl=round(stop_loss, 6),
                     tp=round(take_profit, 6), qty=round(quantity, 6),
                     risk=round(risk_amount, 2))

            return {
                "action": "OPENED",
                "asset": asset,
                "direction": direction,
                "entry_price": entry_price,
                "stop_loss": round(stop_loss, 6),
                "take_profit": round(take_profit, 6),
                "quantity": round(quantity, 6),
                "risk_amount": round(risk_amount, 2),
                "signal_score": consensus_score,
            }

    except Exception as e:
        logger.error("paper_trade_sync_failed", error=str(e), asset=asset)
        import traceback
        logger.error("paper_trade_sync_traceback", tb=traceback.format_exc())
        return {"action": "ERROR", "error": str(e)}
