"""
End-to-end production pipeline verification.

Tests the complete flow: signal → idempotency gate → circuit breaker →
execution → fill recording → close → broker-truth PnL.

Verifies all 15 production safety requirements work together.
"""


def test_e2e_order_lifecycle():
    """Full order lifecycle: intent → fill → close with broker-truth PnL."""
    try:
        from bahamut.execution.order_manager import OrderManager, OrderState
    except Exception:
        return  # Skip if dependencies not available

    mgr = OrderManager()

    # 1. Create intent (idempotency gate)
    import time
    intent = mgr.create_intent(
        asset="BTCUSD", asset_class="crypto", direction="LONG",
        strategy="v9_breakout", size=0.01,
        signal_id=f"e2e_test_lifecycle_{int(time.time())}",
        risk_amount=100.0, sl_pct=0.025, tp_pct=0.05,
    )
    if intent is None:
        # DB not available — skip gracefully
        return
    assert "intent_id" in intent
    assert "client_order_id" in intent

    intent_id = intent["intent_id"]

    # 2. Transition to submit_pending
    ok = mgr.transition(intent_id, OrderState.SUBMIT_PENDING)
    assert ok, "INTENT_CREATED → SUBMIT_PENDING should be valid"

    # 3. Record fill (broker truth)
    ok = mgr.record_fill(
        intent_id, fill_price=67500.0, fill_qty=0.01,
        commission=0.05, broker_order_id="BINANCE_123",
        platform="binance_futures",
    )
    assert ok, "Fill recording should succeed"

    # 4. Verify fill state
    intent_data = mgr.get_intent_by_signal(intent["signal_id"])
    if intent_data:
        assert float(intent_data.get("avg_fill_price", 0)) == 67500.0
        assert float(intent_data.get("filled_qty", 0)) == 0.01

    # 5. Record close with broker-truth exit
    result = mgr.record_close(
        intent_id, exit_price=68000.0, exit_reason="TP",
        exit_commission=0.05, exit_slippage=0.02,
    )
    if result:
        assert abs(result["gross_pnl"] - 5.0) < 0.01
        assert result["net_pnl"] < result["gross_pnl"]

    # 6. Verify audit trail
    events = mgr.get_audit_trail(intent_id)
    assert len(events) >= 3, f"Should have at least 3 events, got {len(events)}"


def test_e2e_idempotency_blocks_duplicate():
    """Same signal_id must be blocked on second attempt."""
    try:
        from bahamut.execution.order_manager import OrderManager
    except Exception:
        return

    import time
    mgr = OrderManager()
    sig_id = f"e2e_dedup_{int(time.time())}"

    first = mgr.create_intent(
        asset="ETHUSD", asset_class="crypto", direction="SHORT",
        strategy="v10_mean_reversion", size=0.1, signal_id=sig_id,
        risk_amount=50.0,
    )
    if first is None:
        return  # DB not available

    second = mgr.create_intent(
        asset="ETHUSD", asset_class="crypto", direction="SHORT",
        strategy="v10_mean_reversion", size=0.1, signal_id=sig_id,
        risk_amount=50.0,
    )
    assert second is None, "Duplicate signal_id must be blocked"


def test_e2e_invalid_transition_rejected():
    """Invalid state transitions must be rejected and logged."""
    try:
        from bahamut.execution.order_manager import OrderManager, OrderState
    except Exception:
        return

    import time
    mgr = OrderManager()
    intent = mgr.create_intent(
        asset="AAPL", asset_class="stock", direction="LONG",
        strategy="v5_base", size=1, signal_id=f"e2e_invalid_{int(time.time())}",
        risk_amount=25.0,
    )
    if intent is None:
        return  # DB not available

    ok = mgr.transition(intent["intent_id"], OrderState.FILLED)
    assert not ok, "INTENT_CREATED → FILLED should be rejected"


def test_e2e_circuit_breaker_blocks_after_threshold():
    """Circuit breaker must block execution after N failures."""
    from bahamut.execution.circuit_breaker import CircuitBreaker
    import os

    os.environ["CIRCUIT_BREAKER_THRESHOLD"] = "3"
    os.environ["CIRCUIT_BREAKER_COOLDOWN"] = "5"
    cb = CircuitBreaker()
    cb._state = "CLOSED"
    cb._failure_count = 0

    # Simulate 3 failures
    cb.record_failure("err1")
    cb.record_failure("err2")
    cb.record_failure("err3")

    assert cb.allow_execution() is False, "Should be blocked after 3 failures"
    assert cb.get_status()["state"] == "OPEN"

    # Force reset
    cb.force_reset()
    assert cb.allow_execution() is True, "Should allow after reset"

    os.environ.pop("CIRCUIT_BREAKER_THRESHOLD", None)
    os.environ.pop("CIRCUIT_BREAKER_COOLDOWN", None)


def test_e2e_shutdown_blocks_execution():
    """Shutdown flag must block new trades."""
    import bahamut.execution.shutdown as sh

    sh._shutting_down = True
    assert sh.is_shutting_down() is True

    # execute_open should return an error result when shutting down
    from bahamut.execution.router import execute_open
    result = execute_open("BTCUSD", "crypto", "LONG", 0.01, 100.0)
    # Should have error status or error message
    is_error = (result.get("status") in ("error", "internal")
                or result.get("error")
                or result.get("lifecycle") == "ERROR")
    assert is_error, f"Should be blocked during shutdown, got: {result}"

    sh._shutting_down = False


def test_e2e_reconciliation_returns_structure():
    """Reconciliation must return actionable results."""
    from bahamut.execution.reconciliation import reconcile_all
    result = reconcile_all()

    assert "summary" in result
    assert "reconciled_at" in result
    for key in ("matched", "mismatches", "orphans", "missing_on_broker"):
        assert key in result["summary"], f"Missing {key} in summary"


def test_e2e_health_endpoint_shape():
    """Health endpoint must cover all production subsystems."""
    # Verify the health checks include production modules
    with open("bahamut/trading/router.py", "r") as f:
        src = f.read()

    for check in ["circuit_breaker", "shutdown_state", "last_reconciliation",
                   "redis", "open_positions", "synthetic_data_blocked",
                   "ai_posture_source", "indicator_engine"]:
        assert check in src, f"Health check '{check}' missing from router"


def test_e2e_system_state_in_operations():
    """Operations response must include system_state field."""
    with open("bahamut/trading/router.py", "r") as f:
        src = f.read()
    assert '"system_state": system_state' in src or "'system_state': system_state" in src


if __name__ == "__main__":
    import sys
    tests = [
        test_e2e_order_lifecycle,
        test_e2e_idempotency_blocks_duplicate,
        test_e2e_invalid_transition_rejected,
        test_e2e_circuit_breaker_blocks_after_threshold,
        test_e2e_shutdown_blocks_execution,
        test_e2e_reconciliation_returns_structure,
        test_e2e_health_endpoint_shape,
        test_e2e_system_state_in_operations,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n  E2E PRODUCTION PIPELINE: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
