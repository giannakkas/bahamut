"""
Sync Paper Trading Executor — for Celery workers.
Uses execution policy as authoritative gate, then sync SQL for trade insertion.
"""
import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from bahamut.database import sync_engine

logger = structlog.get_logger(__name__)


def process_signal_sync(
    asset: str, direction: str, consensus_score: float,
    signal_label: str, entry_price: float, atr: float,
    agent_votes: dict, cycle_id: str = None,
    execution_gate: str = "CLEAR", disagreement_index: float = 0.0,
) -> dict:
    """Sync version of process_signal for Celery workers."""
    import json

    log = logger.bind(asset=asset, direction=direction, score=consensus_score)

    if entry_price <= 0:
        return {"action": "SKIP", "reason": "Invalid price"}

    if signal_label not in ("STRONG_SIGNAL", "SIGNAL"):
        log.info("skip_sync", reason="weak_signal", label=signal_label)
        return {"action": "SKIP", "reason": f"Only SIGNAL+, got {signal_label}"}

    try:
        with sync_engine.connect() as conn:
            # Get or create portfolio
            result = conn.execute(text(
                "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct "
                "FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
            ))
            portfolio = result.mappings().first()

            if not portfolio:
                conn.execute(text(
                    "INSERT INTO paper_portfolios (name, initial_balance, current_balance, peak_balance) "
                    "VALUES ('SYSTEM_DEMO', 100000, 100000, 100000)"
                ))
                conn.commit()
                result = conn.execute(text(
                    "SELECT id, current_balance, is_active, max_open_positions, risk_per_trade_pct "
                    "FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
                ))
                portfolio = result.mappings().first()

            if not portfolio or not portfolio["is_active"]:
                return {"action": "SKIP", "reason": "Portfolio inactive"}

            pid = portfolio["id"]
            balance = portfolio["current_balance"]
            risk_pct = portfolio["risk_per_trade_pct"] or 2.0

            # Count open positions
            open_count = conn.execute(text(
                "SELECT COUNT(*) FROM paper_positions WHERE portfolio_id = :p AND status = 'OPEN'"
            ), {"p": pid}).scalar()

            # Check duplicate
            has_dup = conn.execute(text(
                "SELECT id FROM paper_positions WHERE portfolio_id = :p AND asset = :a AND status = 'OPEN'"
            ), {"p": pid, "a": asset}).first() is not None

            # ── EXECUTION POLICY — authoritative gate ──
            from bahamut.execution.policy import execution_policy, ExecutionRequest
            exec_req = ExecutionRequest(
                asset=asset, direction=direction, consensus_score=consensus_score,
                signal_label=signal_label,
                execution_mode_from_consensus="AUTO" if signal_label == "STRONG_SIGNAL" else "APPROVAL",
                disagreement_gate=execution_gate, disagreement_index=disagreement_index,
                risk_can_trade=execution_gate != "BLOCKED",
                trading_profile="BALANCED",
                open_position_count=open_count, has_position_in_asset=has_dup,
                portfolio_balance=balance,
            )
            decision = execution_policy.evaluate(exec_req)

            if not decision.allowed:
                log.info("blocked_by_policy", reason=decision.reason, blockers=decision.blockers)
                return {"action": "SKIP", "reason": decision.reason,
                        "blockers": decision.blockers, "policy_mode": decision.mode}

            size_mult = decision.position_size_multiplier

            # Calculate SL/TP
            if atr <= 0:
                atr = entry_price * 0.01
            sl_dist = atr * 2.0
            tp_dist = atr * 3.0
            if direction == "LONG":
                sl, tp = entry_price - sl_dist, entry_price + tp_dist
            else:
                sl, tp = entry_price + sl_dist, entry_price - tp_dist

            # Position sizing with policy multiplier
            risk_amt = balance * (risk_pct / 100.0)
            qty = risk_amt / sl_dist if sl_dist > 0 else 1
            pos_val = qty * entry_price
            if size_mult < 1.0:
                qty *= size_mult
                pos_val *= size_mult
                risk_amt *= size_mult

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
                    :risk, :atr, :price, CAST(:votes AS jsonb), :cscore,
                    :cid, 'OPEN', NOW()
                )
            """), {
                "pid": pid, "asset": asset, "dir": direction,
                "price": entry_price, "qty": round(qty, 6), "val": round(pos_val, 2),
                "score": consensus_score, "label": signal_label,
                "sl": round(sl, 6), "tp": round(tp, 6),
                "risk": round(risk_amt, 2), "atr": atr,
                "votes": json.dumps(agent_votes), "cscore": consensus_score,
                "cid": cycle_id,
            })
            conn.commit()

            # Link decision trace
            if cycle_id:
                try:
                    from bahamut.agents.persistence import link_trace_to_position
                    pr = conn.execute(text(
                        "SELECT id FROM paper_positions WHERE cycle_id = :c ORDER BY opened_at DESC LIMIT 1"
                    ), {"c": cycle_id})
                    row = pr.first()
                    if row:
                        link_trace_to_position(cycle_id, row[0])
                except Exception:
                    pass

            log.info("trade_opened_sync", sl=round(sl, 6), tp=round(tp, 6),
                     qty=round(qty, 6), risk=round(risk_amt, 2),
                     policy=decision.mode, size_mult=size_mult)

            return {
                "action": "OPENED", "asset": asset, "direction": direction,
                "entry_price": entry_price, "stop_loss": round(sl, 6),
                "take_profit": round(tp, 6), "quantity": round(qty, 6),
                "risk_amount": round(risk_amt, 2), "signal_score": consensus_score,
                "policy_mode": decision.mode, "size_multiplier": size_mult,
                "policy_warnings": decision.warnings, "cycle_id": cycle_id,
            }

    except Exception as e:
        logger.error("sync_trade_failed", error=str(e), asset=asset)
        import traceback
        logger.error("sync_traceback", tb=traceback.format_exc())
        return {"action": "ERROR", "error": str(e)}
