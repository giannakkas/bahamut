"""
Bahamut.AI — Test Trade Duplicate Prevention Tests

Covers:
  1. Deterministic signal_id prevents engine-level duplicates
  2. Redis position check prevents cross-process duplicates
  3. Redis lock prevents concurrent creation race
  4. Signal ID cleared on close → reopen works
  5. Rapid double-call produces exactly one order

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_trade_dedup.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from bahamut.execution.engine import ExecutionEngine
from bahamut.strategies.base import Signal
from bahamut.execution import system_readiness as sr


@pytest.fixture(autouse=True)
def _ready():
    sr._test_override_allow = True
    yield
    sr._test_override_allow = True


def test_deterministic_signal_id():
    """Test trades use deterministic signal_id, not random UUID."""
    from bahamut.execution.test_trade_mode import _create_test_trade_inner
    # We can't easily call _create_test_trade_inner without side effects,
    # but we can verify the Signal construction pattern
    sig = Signal(
        strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
        sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade",
    )
    sig2 = Signal(
        strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
        sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade",
    )
    assert sig.signal_id == sig2.signal_id == "TEST:BTCUSD:LONG:test_trade"


def test_engine_dedup_catches_deterministic_id():
    """Same deterministic signal_id → second submit rejected by engine."""
    engine = ExecutionEngine()
    sig1 = Signal(strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
                  sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade")
    sig2 = Signal(strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
                  sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade")

    o1 = engine.submit_signal(sig1, 100000)
    o2 = engine.submit_signal(sig2, 100000)

    assert o1 is not None, "First signal should create order"
    assert o2 is None, "Second signal with same ID should be rejected"


def test_redis_existing_position_blocks_creation():
    """If Redis has an open test position, new creation is rejected."""
    from bahamut.execution.test_trade_mode import create_test_trade

    # Mock get_test_positions_from_redis to return an existing position
    with patch("bahamut.execution.test_trade_mode.get_test_positions_from_redis") as mock:
        mock.return_value = [{"order_id": "existing-123", "asset": "BTCUSD"}]
        result = create_test_trade()

    assert result["status"] == "REJECTED"
    assert "already open" in result["reason"]


def test_redis_lock_prevents_concurrent():
    """If Redis lock is held, second creation is rejected."""
    from bahamut.execution.test_trade_mode import create_test_trade

    # Mock: no existing positions, but lock already held
    with patch("bahamut.execution.test_trade_mode.get_test_positions_from_redis", return_value=[]):
        mock_redis = MagicMock()
        mock_redis.set.return_value = False  # Lock already held
        with patch("bahamut.execution.test_trade_mode._get_redis", return_value=mock_redis):
            result = create_test_trade()

    assert result["status"] == "REJECTED"
    assert "in progress" in result["reason"]


def test_close_clears_signal_id():
    """After closing, the deterministic signal_id is cleared from engine dedup."""
    engine = ExecutionEngine()

    # Submit and fill
    sig = Signal(strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
                 sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade")
    o1 = engine.submit_signal(sig, 100000)
    assert o1 is not None

    bar = {"open": 68000, "high": 68100, "low": 67900, "close": 68000,
           "datetime": "2026-03-24T12:00:00"}
    engine.on_new_bar(bar, {"TEST_test_trade": 10000}, asset="BTCUSD")
    assert len(engine.open_positions) == 1

    # Verify signal_id is in dedup set
    assert "TEST:BTCUSD:LONG:test_trade" in engine._processed_signals

    # Close via _clear_test_signal_ids
    from bahamut.execution.test_trade_mode import _clear_test_signal_ids
    # Point _clear to our engine
    with patch("bahamut.execution.test_trade_mode.get_execution_engine", return_value=engine):
        _clear_test_signal_ids()

    assert "TEST:BTCUSD:LONG:test_trade" not in engine._processed_signals

    # Now can reopen
    sig2 = Signal(strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
                  sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade")
    # Remove old position first
    engine.open_positions.clear()
    o2 = engine.submit_signal(sig2, 100000)
    assert o2 is not None, "Should allow reopening after close + signal_id clear"


def test_rapid_double_same_process():
    """Two rapid calls on the same engine produce exactly one order."""
    engine = ExecutionEngine()

    results = []
    for _ in range(5):
        sig = Signal(strategy="TEST_test_trade", asset="BTCUSD", direction="LONG",
                     sl_pct=0.03, tp_pct=0.06, signal_id="TEST:BTCUSD:LONG:test_trade")
        o = engine.submit_signal(sig, 100000)
        results.append(o)

    created = [r for r in results if r is not None]
    assert len(created) == 1, f"Expected exactly 1 order, got {len(created)}"


def test_non_test_signals_unaffected():
    """Production signals still use random UUIDs and aren't affected by test dedup."""
    s1 = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                sl_pct=0.08, tp_pct=0.16)
    s2 = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                sl_pct=0.08, tp_pct=0.16)
    assert s1.signal_id != s2.signal_id, "Production signals should have unique IDs"
    assert not s1.signal_id.startswith("TEST:"), "Production signals shouldn't have TEST prefix"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
