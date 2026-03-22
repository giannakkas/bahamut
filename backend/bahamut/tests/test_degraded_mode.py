"""
Bahamut.AI — Degraded Mode & Fail-Safe Tests

Covers:
  1. DB down at startup → no-trade mode
  2. Reconciliation gates new entries
  3. Stale data blocks signal generation per-asset
  4. Positions still monitored when entries blocked
  5. Recovery resumes trading
  6. System readiness API truthfulness

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_degraded_mode.py -v
"""
import pytest
import time
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

def _fresh_readiness():
    """Reset readiness state for test isolation."""
    from bahamut.execution import system_readiness as sr
    sr._state["reconciliation_complete"] = False
    sr._state["reconciliation_error"] = ""
    sr._state["db_last_ok"] = 0.0
    sr._state["db_last_error"] = ""
    sr._state["asset_data_health"] = {}


# ═══════════════════════════════════════════
# 1. RECONCILIATION GATES NEW ENTRIES
# ═══════════════════════════════════════════

def test_unreconciled_blocks_system_trade():
    """Before reconciliation completes, can_system_trade must return False."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import can_system_trade

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is False
    assert any("RECONCIL" in r.upper() for r in reasons), f"Expected reconciliation reason, got: {reasons}"


def test_reconciled_allows_system_trade():
    """After successful reconciliation + fresh data, can_system_trade returns True."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=60)

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is True, f"Should allow trading after reconciliation. Reasons: {reasons}"
    assert len(reasons) == 0


def test_unreconciled_engine_rejects_signal():
    """submit_signal must reject when system readiness gate fails."""
    _fresh_readiness()  # reconciliation_complete = False
    from bahamut.execution.engine import ExecutionEngine
    from bahamut.strategies.base import Signal

    engine = ExecutionEngine()

    sig = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                 signal_id="gate-test-1", sl_pct=0.08, tp_pct=0.16)
    order = engine.submit_signal(sig, 50000)

    assert order is None, "Engine should reject signals before reconciliation"


def test_reconciled_engine_accepts_signal():
    """submit_signal must accept when system is fully ready."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        mark_reconciliation_success, update_asset_data_health,
    )
    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=60)

    from bahamut.execution.engine import ExecutionEngine
    from bahamut.strategies.base import Signal

    engine = ExecutionEngine()
    sig = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                 signal_id="gate-test-2", sl_pct=0.08, tp_pct=0.16)
    order = engine.submit_signal(sig, 50000)

    assert order is not None, "Engine should accept signals when system is ready"


# ═══════════════════════════════════════════
# 2. DB DOWN AT STARTUP → NO-TRADE MODE
# ═══════════════════════════════════════════

def test_db_down_reconciliation_marks_failed():
    """If DB is down during reconciliation, reconciliation_complete stays False."""
    _fresh_readiness()
    from bahamut.execution.engine import ExecutionEngine, _reconcile_from_db

    engine = ExecutionEngine()

    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("DB connection refused")

    with patch("bahamut.database.sync_engine", mock_engine):
        _reconcile_from_db(engine)

    from bahamut.execution.system_readiness import is_reconciled
    assert is_reconciled() is False, "Reconciliation should be marked as failed"


def test_db_down_blocks_new_entries():
    """DB down at startup → new entries must be blocked."""
    _fresh_readiness()
    from bahamut.execution.engine import ExecutionEngine, _reconcile_from_db
    from bahamut.strategies.base import Signal

    engine = ExecutionEngine()

    mock_eng = MagicMock()
    mock_eng.connect.side_effect = Exception("DB down")
    with patch("bahamut.database.sync_engine", mock_eng):
        _reconcile_from_db(engine)

    sig = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                 signal_id="db-down-test", sl_pct=0.08, tp_pct=0.16)
    order = engine.submit_signal(sig, 50000)
    assert order is None, "Should block new entries when DB was down at startup"


# ═══════════════════════════════════════════
# 3. STALE DATA BLOCKS SIGNAL GENERATION
# ═══════════════════════════════════════════

def test_stale_data_blocks_asset():
    """Stale market data (>6h) must block new entries for that asset."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "STALE", age_seconds=25000)

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is False
    assert any("DATA_NOT_FRESH" in r for r in reasons), f"Expected data freshness reason, got: {reasons}"


def test_missing_data_blocks_asset():
    """Missing data must block new entries."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "MISSING")

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is False


def test_fresh_data_allows_asset():
    """Fresh data (<15min) must allow new entries."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=300)

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is True, f"Fresh data should allow trading. Reasons: {reasons}"


def test_degraded_data_allows_asset():
    """Degraded data (15min-6h) should still allow trading."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "DEGRADED", age_seconds=3000)

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is True, "Degraded data should still allow trading"


def test_per_asset_isolation():
    """BTCUSD stale must NOT block ETHUSD if ETH data is fresh."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "STALE", age_seconds=30000)
    update_asset_data_health("ETHUSD", "HEALTHY", age_seconds=100)

    btc_can, _ = can_system_trade(asset="BTCUSD")
    eth_can, _ = can_system_trade(asset="ETHUSD")

    assert btc_can is False, "BTC should be blocked (stale)"
    assert eth_can is True, "ETH should be allowed (fresh)"


def test_no_data_recorded_blocks_asset():
    """If no data health has been recorded for an asset, it must be blocked."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import can_system_trade, mark_reconciliation_success

    mark_reconciliation_success()
    # No update_asset_data_health called for BTCUSD

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is False, "No data recorded should block trading"


# ═══════════════════════════════════════════
# 4. POSITIONS MONITORED WHEN ENTRIES BLOCKED
# ═══════════════════════════════════════════

def test_position_monitoring_continues_when_blocked():
    """Even when new entries are blocked, on_new_bar must still process exits."""
    _fresh_readiness()  # Not reconciled → entries blocked

    from bahamut.execution.engine import ExecutionEngine
    from bahamut.execution.models import Position, OrderStatus

    engine = ExecutionEngine()

    # Manually add an open position (simulating pre-existing state)
    pos = Position(
        order_id="monitor-test", strategy="v5_base", asset="BTCUSD",
        direction="LONG", status=OrderStatus.OPEN,
        entry_price=68000, current_price=68000,
        stop_price=62000, tp_price=75000,
        size=0.01, risk_amount=600,
        max_hold_bars=3, bars_held=0,
    )
    engine.open_positions.append(pos)

    # Process bars → should still monitor and close via timeout
    for i in range(5):
        bar = {"open": 68000, "high": 68100, "low": 67900, "close": 68000,
               "datetime": f"t{i}"}
        engine.on_new_bar(bar, {"v5_base": 50000}, asset="BTCUSD")

    assert len(engine.open_positions) == 0, "Position should be closed by timeout"
    assert len(engine.closed_trades) == 1, "Closed trade should be recorded"
    assert engine.closed_trades[0].exit_reason == "TIMEOUT"


def test_new_entry_blocked_but_exit_works():
    """New signal rejected while existing position still closes normally."""
    _fresh_readiness()  # entries blocked
    from bahamut.execution.engine import ExecutionEngine
    from bahamut.execution.models import Position, OrderStatus
    from bahamut.strategies.base import Signal

    engine = ExecutionEngine()

    # Pre-existing position
    engine.open_positions.append(Position(
        order_id="exit-test", strategy="v5_base", asset="BTCUSD",
        direction="LONG", status=OrderStatus.OPEN,
        entry_price=68000, current_price=68000,
        stop_price=62000, tp_price=75000,
        size=0.01, risk_amount=600, max_hold_bars=2,
    ))

    # New signal should be rejected
    sig = Signal(strategy="v5_tuned", asset="BTCUSD", direction="LONG",
                 signal_id="blocked-entry", sl_pct=0.08, tp_pct=0.16)
    order = engine.submit_signal(sig, 50000)
    assert order is None, "New entry should be blocked"

    # But existing position should still be monitored
    for i in range(3):
        engine.on_new_bar({"open": 68000, "high": 68100, "low": 67900,
                           "close": 68000, "datetime": f"t{i}"},
                          {"v5_base": 50000}, asset="BTCUSD")

    assert len(engine.closed_trades) == 1, "Existing position should still close"


# ═══════════════════════════════════════════
# 5. RECOVERY RESUMES TRADING
# ═══════════════════════════════════════════

def test_recovery_after_reconciliation():
    """After reconciliation succeeds, trading should resume."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    # Initially blocked
    can, _ = can_system_trade(asset="BTCUSD")
    assert can is False

    # Reconciliation succeeds + data fresh
    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=60)

    # Now allowed
    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is True, f"Should resume after recovery. Reasons: {reasons}"


def test_recovery_after_data_refresh():
    """Asset blocked by stale data should unblock when data becomes fresh."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        can_system_trade, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "STALE", age_seconds=30000)

    can, _ = can_system_trade(asset="BTCUSD")
    assert can is False

    # Data refreshes
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=100)

    can, reasons = can_system_trade(asset="BTCUSD")
    assert can is True, f"Should resume after data refresh. Reasons: {reasons}"


# ═══════════════════════════════════════════
# 6. READINESS API TRUTHFULNESS
# ═══════════════════════════════════════════

def test_readiness_state_shape():
    """get_readiness_state must return all required fields."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import get_readiness_state

    state = get_readiness_state()

    required = ["can_trade", "reasons", "reconciliation_complete",
                "reconciliation_error", "db_healthy", "assets"]
    for field in required:
        assert field in state, f"Missing required field: {field}"


def test_readiness_reflects_unreconciled():
    """Readiness API must show reconciliation_complete=False when not reconciled."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import get_readiness_state

    state = get_readiness_state()
    assert state["can_trade"] is False
    assert state["reconciliation_complete"] is False


def test_readiness_reflects_healthy():
    """Readiness API must show can_trade=True when fully healthy."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        get_readiness_state, mark_reconciliation_success,
        update_asset_data_health, mark_db_ok,
    )

    mark_reconciliation_success()
    mark_db_ok()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=60)

    state = get_readiness_state()
    assert state["can_trade"] is True
    assert state["reconciliation_complete"] is True
    assert state["db_healthy"] is True


def test_readiness_per_asset_detail():
    """Readiness API must show per-asset data status."""
    _fresh_readiness()
    from bahamut.execution.system_readiness import (
        get_readiness_state, mark_reconciliation_success, update_asset_data_health,
    )

    mark_reconciliation_success()
    update_asset_data_health("BTCUSD", "HEALTHY", age_seconds=60)
    update_asset_data_health("ETHUSD", "STALE", age_seconds=30000)

    state = get_readiness_state()
    assert "BTCUSD" in state["assets"]
    assert "ETHUSD" in state["assets"]
    assert state["assets"]["BTCUSD"]["can_trade"] is True
    assert state["assets"]["ETHUSD"]["can_trade"] is False
    assert state["assets"]["ETHUSD"]["data_status"] == "STALE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
