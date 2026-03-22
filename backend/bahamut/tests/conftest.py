"""
Shared test fixtures for Bahamut tests.

Most tests assume the system is in a ready state.
The degraded_mode tests explicitly override this with _fresh_readiness().
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_system_readiness():
    """Reset system readiness to 'ready' before each test.

    This ensures the readiness gate doesn't interfere with tests that
    construct bare ExecutionEngine instances. Tests that specifically
    test degraded behavior call _fresh_readiness() to override.
    """
    try:
        from bahamut.execution import system_readiness as sr
        sr._state["reconciliation_complete"] = True
        sr._state["reconciliation_error"] = ""
        sr._state["db_last_ok"] = __import__("time").time()
        sr._state["db_last_error"] = ""
        sr._state["asset_data_health"] = {
            "BTCUSD": {"status": "HEALTHY", "age_seconds": 60, "updated_at": __import__("time").time()},
            "ETHUSD": {"status": "HEALTHY", "age_seconds": 60, "updated_at": __import__("time").time()},
            "TEST": {"status": "HEALTHY", "age_seconds": 60, "updated_at": __import__("time").time()},
        }
    except Exception:
        pass  # system_readiness may not be importable in all test contexts
    yield
