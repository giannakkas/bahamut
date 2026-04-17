"""
Production safety module tests — Order Manager, Circuit Breaker,
Reconciliation, Shutdown.
"""
import time
import os


# ═══════════════════════════════════════════
# ORDER MANAGER TESTS
# ═══════════════════════════════════════════

def test_order_state_transitions_valid():
    """Valid state transitions must be allowed."""
    from bahamut.execution.order_manager import OrderState, _VALID_TRANSITIONS
    # intent → submit_pending
    assert OrderState.SUBMIT_PENDING in _VALID_TRANSITIONS[OrderState.INTENT_CREATED]
    # submitted → filled
    assert OrderState.FILLED in _VALID_TRANSITIONS[OrderState.SUBMITTED]
    # filled → closed
    assert OrderState.CLOSED in _VALID_TRANSITIONS[OrderState.FILLED]
    # partial → filled
    assert OrderState.FILLED in _VALID_TRANSITIONS[OrderState.PARTIALLY_FILLED]


def test_order_state_transitions_terminal():
    """Terminal states (REJECTED, CANCELED, CLOSED) allow no transitions."""
    from bahamut.execution.order_manager import OrderState, _VALID_TRANSITIONS
    assert _VALID_TRANSITIONS[OrderState.REJECTED] == set()
    assert _VALID_TRANSITIONS[OrderState.CANCELED] == set()
    assert _VALID_TRANSITIONS[OrderState.CLOSED] == set()


def test_order_state_unknown_to_reconcile():
    """Submission unknown must allow recovery via reconciliation."""
    from bahamut.execution.order_manager import OrderState, _VALID_TRANSITIONS
    assert OrderState.RECONCILE_REQUIRED in _VALID_TRANSITIONS[OrderState.SUBMISSION_UNKNOWN]
    assert OrderState.FILLED in _VALID_TRANSITIONS[OrderState.SUBMISSION_UNKNOWN]
    assert OrderState.REJECTED in _VALID_TRANSITIONS[OrderState.SUBMISSION_UNKNOWN]


def test_order_state_error_recovery():
    """ERROR state can recover to RECONCILE_REQUIRED."""
    from bahamut.execution.order_manager import OrderState, _VALID_TRANSITIONS
    assert OrderState.RECONCILE_REQUIRED in _VALID_TRANSITIONS[OrderState.ERROR]


def test_position_states_exist():
    """All position states defined."""
    from bahamut.execution.order_manager import PositionState
    for state in ("OPENING", "OPEN", "REDUCING", "CLOSING", "CLOSED", "UNKNOWN"):
        assert hasattr(PositionState, state)


def test_order_manager_instantiates():
    """OrderManager can be created without crashing."""
    from bahamut.execution.order_manager import OrderManager
    mgr = OrderManager()
    assert mgr is not None


def test_execution_lock_logic():
    """Execution lock acquire/release pattern works."""
    from bahamut.execution.order_manager import OrderManager
    mgr = OrderManager()
    # Without Redis, acquire always returns True (fallback)
    assert mgr.acquire_execution_lock("BTCUSD", "LONG") is True
    mgr.release_execution_lock("BTCUSD", "LONG")


# ═══════════════════════════════════════════
# CIRCUIT BREAKER TESTS
# ═══════════════════════════════════════════

def test_circuit_breaker_starts_closed():
    from bahamut.execution.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    status = cb.get_status()
    assert status["state"] == "CLOSED"
    assert cb.allow_execution() is True


def test_circuit_breaker_trips_after_threshold():
    from bahamut.execution.circuit_breaker import CircuitBreaker
    os.environ["CIRCUIT_BREAKER_THRESHOLD"] = "3"
    os.environ["CIRCUIT_BREAKER_COOLDOWN"] = "60"
    cb = CircuitBreaker()
    cb._failure_count = 0
    cb._state = "CLOSED"

    cb.record_failure("err1")
    cb.record_failure("err2")
    assert cb.allow_execution() is True  # 2 < 3

    cb.record_failure("err3")
    assert cb.get_status()["state"] == "OPEN"
    assert cb.allow_execution() is False

    os.environ.pop("CIRCUIT_BREAKER_THRESHOLD", None)
    os.environ.pop("CIRCUIT_BREAKER_COOLDOWN", None)


def test_circuit_breaker_recovers_on_success():
    from bahamut.execution.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb._state = "HALF_OPEN"
    cb._half_open_attempts = 0

    # In half-open, one attempt is allowed
    assert cb.allow_execution() is True
    cb.record_success()
    assert cb.get_status()["state"] == "CLOSED"


def test_circuit_breaker_force_reset():
    from bahamut.execution.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb._state = "OPEN"
    cb._failure_count = 10
    cb.force_reset()
    assert cb.get_status()["state"] == "CLOSED"
    assert cb.get_status()["failure_count"] == 0


def test_circuit_breaker_status_shape():
    from bahamut.execution.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    s = cb.get_status()
    for key in ("state", "failure_count", "success_count",
                "threshold", "cooldown_seconds", "remaining_cooldown"):
        assert key in s, f"missing {key}"


# ═══════════════════════════════════════════
# SHUTDOWN HANDLER TESTS
# ═══════════════════════════════════════════

def test_is_shutting_down_default_false():
    from bahamut.execution.shutdown import is_shutting_down
    # Fresh import — not shutting down
    import bahamut.execution.shutdown as sh
    sh._shutting_down = False
    assert is_shutting_down() is False


def test_shutdown_flag_blocks():
    import bahamut.execution.shutdown as sh
    sh._shutting_down = True
    assert sh.is_shutting_down() is True
    sh._shutting_down = False  # cleanup


# ═══════════════════════════════════════════
# RECONCILIATION TESTS
# ═══════════════════════════════════════════

def test_reconciliation_module_importable():
    from bahamut.execution.reconciliation import reconcile_all, get_last_reconciliation
    assert callable(reconcile_all)
    assert callable(get_last_reconciliation)


def test_reconciliation_returns_structure():
    """reconcile_all returns expected dict shape even without broker access."""
    from bahamut.execution.reconciliation import reconcile_all
    result = reconcile_all()
    assert "summary" in result
    assert "reconciled_at" in result
    for key in ("matched", "mismatches", "orphans", "missing_on_broker"):
        assert key in result["summary"]


if __name__ == "__main__":
    import sys
    tests = [
        # Order Manager
        test_order_state_transitions_valid,
        test_order_state_transitions_terminal,
        test_order_state_unknown_to_reconcile,
        test_order_state_error_recovery,
        test_position_states_exist,
        test_order_manager_instantiates,
        test_execution_lock_logic,
        # Circuit Breaker
        test_circuit_breaker_starts_closed,
        test_circuit_breaker_trips_after_threshold,
        test_circuit_breaker_recovers_on_success,
        test_circuit_breaker_force_reset,
        test_circuit_breaker_status_shape,
        # Shutdown
        test_is_shutting_down_default_false,
        test_shutdown_flag_blocks,
        # Reconciliation
        test_reconciliation_module_importable,
        test_reconciliation_returns_structure,
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
    print(f"\n  PRODUCTION SAFETY SUITE: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
