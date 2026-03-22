"""
Shared test fixtures for Bahamut tests.

Most tests assume the system is in a ready state.
The degraded_mode tests explicitly override this with _fresh_readiness().
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_system_readiness():
    """Reset system readiness to 'ready' before each test.

    Uses the public API which writes to Redis (or no-ops if Redis unavailable).
    Also patches can_system_trade to always return True for non-degraded tests.
    """
    try:
        from bahamut.execution import system_readiness as sr
        # For tests without Redis, patch the gate to always allow
        sr._test_override_allow = True
    except Exception:
        pass
    yield
    try:
        from bahamut.execution import system_readiness as sr
        sr._test_override_allow = False
    except Exception:
        pass
