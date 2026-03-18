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
    risk_flags: list = None, risk_can_trade: bool = True,
    regime: str = "RISK_ON", trading_profile: str = "BALANCED",
) -> dict:
    """Sync version of process_signal for Celery workers."""
    import json
    risk_flags = risk_flags or []

    log = logger.bind(asset=asset, direction=direction, score=consensus_score)

    if entry_price <= 0:
        return {"action": "SKIP", "reason": "Invalid price"}

    # ── PRIMARY GATE: Disagreement (checked first, unconditionally) ──
    if execution_gate == "BLOCKED":
        log.info("primary_gate_blocked", reason="disagreement",
                 index=disagreement_index)
        return {"action": "SKIP", "reason": f"Disagreement BLOCKED (index={disagreement_index:.3f})",
                "gate": "DISAGREEMENT", "disagreement_index": disagreement_index}

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

            # ── PORTFOLIO INTELLIGENCE — evaluates trade in portfolio context ──
            portfolio_verdict = None
            portfolio_size_mult = 1.0
            try:
                from bahamut.portfolio.registry import load_portfolio_snapshot
                from bahamut.portfolio.engine import evaluate_trade_for_portfolio

                snap = load_portfolio_snapshot()
                # Estimate proposed position value
                sl_est = (atr * 2.0) if atr > 0 else (entry_price * 0.01)
                risk_est = balance * (risk_pct / 100.0)
                qty_est = risk_est / sl_est if sl_est > 0 else 1
                val_est = qty_est * entry_price

                portfolio_verdict = evaluate_trade_for_portfolio(
                    snapshot=snap,
                    proposed_asset=asset,
                    proposed_direction=direction,
                    proposed_value=val_est,
                    proposed_risk=risk_est,
                    consensus_score=consensus_score,
                )

                if not portfolio_verdict.allowed:
                    log.info("blocked_by_portfolio", blockers=portfolio_verdict.blockers)
                    return {"action": "SKIP", "reason": portfolio_verdict.blockers[0],
                            "blockers": portfolio_verdict.blockers, "gate": "PORTFOLIO"}

                portfolio_size_mult = portfolio_verdict.size_multiplier
            except Exception as e:
                log.debug("portfolio_intel_skipped", error=str(e))

            # ── EXECUTION POLICY — authoritative gate ──
            # Compute system confidence (composite of trust stability,
            # disagreement trend, recent performance, calibration health)
            sys_conf = 0.5
            mean_trust = 1.0
            try:
                from bahamut.consensus.system_confidence import get_system_confidence
                bd = get_system_confidence()
                sys_conf = bd.system_confidence
                mean_trust = bd.mean_agent_trust
            except Exception:
                pass

            # Feed portfolio intelligence into execution policy
            augmented_flags = list(risk_flags)
            if portfolio_verdict:
                for w in portfolio_verdict.warnings:
                    if "CORRELATED" in w or "CLASS_CONCENTRATION" in w:
                        augmented_flags.append("HIGH_CORRELATION")
                    if "THEME_CONCENTRATION" in w or "THEME_OVERLAP" in w:
                        augmented_flags.append("HIGH_EXPOSURE")
                if portfolio_verdict.requires_approval:
                    augmented_flags.append("PORTFOLIO_FRAGILE")

            from bahamut.execution.policy import execution_policy, ExecutionRequest
            exec_req = ExecutionRequest(
                asset=asset, direction=direction, consensus_score=consensus_score,
                signal_label=signal_label,
                execution_mode_from_consensus="AUTO" if signal_label == "STRONG_SIGNAL" else "APPROVAL",
                disagreement_gate=execution_gate, disagreement_index=disagreement_index,
                risk_flags=augmented_flags,
                risk_can_trade=risk_can_trade,
                trading_profile=trading_profile,
                open_position_count=open_count, has_position_in_asset=has_dup,
                portfolio_balance=balance,
                mean_agent_trust=mean_trust,
                system_confidence=sys_conf,
                regime=regime,
            )
            decision = execution_policy.evaluate(exec_req)

            if not decision.allowed:
                log.info("blocked_by_policy", reason=decision.reason, blockers=decision.blockers)
                return {"action": "SKIP", "reason": decision.reason,
                        "blockers": decision.blockers, "policy_mode": decision.mode}

            size_mult = decision.position_size_multiplier

            # Combine with portfolio intelligence sizing
            if portfolio_size_mult < 1.0:
                size_mult *= portfolio_size_mult
                log.info("portfolio_sizing", policy_mult=decision.position_size_multiplier,
                         portfolio_mult=portfolio_size_mult, combined=size_mult)

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

            # Insert position with execution context
            conn.execute(text("""
                INSERT INTO paper_positions (
                    portfolio_id, asset, direction, entry_price, quantity, position_value,
                    entry_signal_score, entry_signal_label, stop_loss, take_profit,
                    risk_amount, atr_at_entry, current_price, agent_votes, consensus_score,
                    cycle_id, status, opened_at,
                    trading_profile, regime, disagreement_index, execution_mode
                ) VALUES (
                    :pid, :asset, :dir, :price, :qty, :val,
                    :score, :label, :sl, :tp,
                    :risk, :atr, :price, CAST(:votes AS jsonb), :cscore,
                    :cid, 'OPEN', NOW(),
                    :profile, :regime, :disagree, :exec_mode
                )
            """), {
                "pid": pid, "asset": asset, "dir": direction,
                "price": entry_price, "qty": round(qty, 6), "val": round(pos_val, 2),
                "score": consensus_score, "label": signal_label,
                "sl": round(sl, 6), "tp": round(tp, 6),
                "risk": round(risk_amt, 2), "atr": atr,
                "votes": json.dumps(agent_votes), "cscore": consensus_score,
                "cid": cycle_id,
                "profile": trading_profile, "regime": regime,
                "disagree": disagreement_index, "exec_mode": decision.mode,
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
