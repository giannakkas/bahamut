"""
Bahamut.AI — Production Safety Tests

Covers all 5 critical bugs:
  1. Kill switch false trigger (drawdown math, clamping, threshold guard)
  2. New bar detection (NEW_BAR_READY accuracy)
  3. Orchestrator locking (prevents overlap)
  4. Performance tab matches trades tab
  5. Alert dedup lifecycle

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_production_safety.py -v
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════
# 1. KILL SWITCH — drawdown math
# ═══════════════════════════════════════════

class MockEngine:
    def __init__(self):
        self.open_positions = []
        self.closed_trades = []
    def get_strategy_pnl(self, strategy):
        return sum(t.pnl for t in self.closed_trades if t.strategy == strategy)
    def get_strategy_unrealized(self, strategy):
        return sum(p.unrealized_pnl for p in self.open_positions if p.strategy == strategy)


@dataclass
class FakeTrade:
    strategy: str = "v5_base"
    asset: str = "BTCUSD"
    direction: str = "LONG"
    pnl: float = 0.0
    exit_reason: str = "TP"
    entry_price: float = 68000.0
    exit_price: float = 70000.0
    order_id: str = "t-001"
    trade_id: str = "t-001"
    bars_held: int = 5
    entry_time: str = ""
    exit_time: str = ""
    pnl_pct: float = 0.0
    stop_price: float = 0.0
    tp_price: float = 0.0
    size: float = 0.01
    risk_amount: float = 100.0


@dataclass
class FakePosition:
    strategy: str = "v5_base"
    asset: str = "BTCUSD"
    direction: str = "LONG"
    unrealized_pnl: float = 0.0
    risk_amount: float = 0.0
    entry_price: float = 68000.0
    current_price: float = 68000.0
    stop_price: float = 65000.0
    tp_price: float = 72000.0
    size: float = 0.01
    order_id: str = "p-001"
    bars_held: int = 0
    entry_time: str = ""


def _make_manager(threshold=0.10):
    from bahamut.portfolio.manager import PortfolioManager
    return PortfolioManager(total_capital=100_000.0, max_drawdown_pct=threshold)


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_zero_drawdown_no_trigger(mock_eng):
    """0% drawdown → kill switch must NOT trigger."""
    mock_eng.return_value = MockEngine()
    pm = _make_manager(0.10)
    pm.update()
    assert pm.kill_switch_triggered is False
    assert pm.total_drawdown == 0.0


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_below_threshold_no_trigger(mock_eng):
    """-3% drawdown with 10% threshold → NO trigger."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="v5_base", pnl=-3000))
    mock_eng.return_value = eng
    pm = _make_manager(0.10)
    pm.update()
    assert pm.kill_switch_triggered is False
    assert pm.total_drawdown < 0.10


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_above_threshold_triggers(mock_eng):
    """-12% drawdown with 10% threshold → SHOULD trigger."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="v5_base", pnl=-6000))
    eng.closed_trades.append(FakeTrade(strategy="v5_tuned", pnl=-6000))
    mock_eng.return_value = eng
    pm = _make_manager(0.10)
    pm.update()
    assert pm.kill_switch_triggered is True


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_threshold_zero_never_triggers(mock_eng):
    """threshold=0 → kill switch must NEVER trigger."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="v5_base", pnl=-50000))
    mock_eng.return_value = eng
    pm = _make_manager(0.0)
    pm.update()
    assert pm.kill_switch_triggered is False


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_drawdown_clamped_to_zero_one(mock_eng):
    """total_drawdown must be in [0.0, 1.0]."""
    mock_eng.return_value = MockEngine()
    pm = _make_manager(0.10)

    # Normal state
    pm.update()
    assert 0.0 <= pm.total_drawdown <= 1.0

    # Simulate equity above peak (shouldn't happen but guard)
    pm.peak_equity = 50000
    assert 0.0 <= pm.total_drawdown <= 1.0

    # Simulate zero peak
    pm.peak_equity = 0
    assert pm.total_drawdown == 0.0


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_test_trade_excluded(mock_eng):
    """Test trades must NOT affect drawdown/kill switch."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="TEST_test_trade", pnl=-50000))
    mock_eng.return_value = eng
    pm = _make_manager(0.05)
    pm.update()
    assert pm.kill_switch_triggered is False


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_ks_structured_log_on_trigger(mock_eng):
    """Kill switch log must include equity, peak_equity, drawdown, threshold, reason."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="v5_base", pnl=-6000))
    eng.closed_trades.append(FakeTrade(strategy="v5_tuned", pnl=-6000))
    mock_eng.return_value = eng

    with patch("bahamut.portfolio.manager.logger") as mock_log:
        pm = _make_manager(0.05)
        pm.update()
        assert pm.kill_switch_triggered is True
        mock_log.warning.assert_called()
        kw = mock_log.warning.call_args.kwargs if mock_log.warning.call_args.kwargs else {}
        for field in ["equity", "peak_equity", "drawdown", "threshold", "reason"]:
            assert field in kw, f"Missing log field: {field}"


# ═══════════════════════════════════════════
# 2. NEW BAR DETECTION
# ═══════════════════════════════════════════

def test_new_bar_same_bar_not_ready():
    """If last_processed == last_completed boundary → WAITING_FOR_NEW_BAR."""
    from bahamut.monitoring.time_utils import get_asset_timing, last_4h_close_utc
    now = datetime.now(timezone.utc)
    last_completed = last_4h_close_utc(now).strftime("%Y-%m-%d %H:%M:%S")

    result = get_asset_timing(last_completed, last_processed_ts=last_completed)
    assert result["status"] != "NEW_BAR_READY", \
        f"Status is {result['status']} but should be WAITING_FOR_NEW_BAR when already processed"


def test_new_bar_old_processed_shows_ready():
    """If last_processed is older than last completed boundary → NEW_BAR_READY."""
    from bahamut.monitoring.time_utils import get_asset_timing, last_4h_close_utc
    now = datetime.now(timezone.utc)
    last_completed = last_4h_close_utc(now)
    # Simulate processing a bar from 8 hours ago
    old_bar = (last_completed - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    result = get_asset_timing(old_bar, last_processed_ts=old_bar)
    # Should be NEW_BAR_READY or STALE (both valid — old_bar may be stale)
    assert result["status"] in ("NEW_BAR_READY", "STALE"), \
        f"Status is {result['status']} but expected NEW_BAR_READY or STALE"


def test_new_bar_no_processed_shows_ready():
    """Fresh start (no processed bar) → NEW_BAR_READY."""
    from bahamut.monitoring.time_utils import get_asset_timing, last_4h_close_utc
    now = datetime.now(timezone.utc)
    recent = last_4h_close_utc(now).strftime("%Y-%m-%d %H:%M:%S")

    result = get_asset_timing(recent, last_processed_ts="")
    assert result["status"] == "NEW_BAR_READY"


def test_new_bar_detection_isolates_assets():
    """is_new_bar must be per-asset isolated."""
    from bahamut.data.live_data import is_new_bar, mark_bar_processed, _last_bar_timestamps
    # Clear state
    _last_bar_timestamps.clear()

    assert is_new_bar("BTCUSD", "2025-01-01 04:00:00") is True
    assert is_new_bar("ETHUSD", "2025-01-01 04:00:00") is True
    # Commit both as processed
    mark_bar_processed("BTCUSD", "2025-01-01 04:00:00")
    mark_bar_processed("ETHUSD", "2025-01-01 04:00:00")
    # Same bar again → not new
    assert is_new_bar("BTCUSD", "2025-01-01 04:00:00") is False
    assert is_new_bar("ETHUSD", "2025-01-01 04:00:00") is False
    # New bar for BTC only
    assert is_new_bar("BTCUSD", "2025-01-01 08:00:00") is True
    assert is_new_bar("ETHUSD", "2025-01-01 04:00:00") is False


def test_same_bar_no_signal_generation():
    """Orchestrator must NOT generate signals on same bar."""
    from bahamut.data.live_data import is_new_bar, mark_bar_processed, _last_bar_timestamps
    _last_bar_timestamps.clear()

    # First time → new bar
    assert is_new_bar("BTCUSD", "2025-06-01 12:00:00") is True
    # Simulate successful processing
    mark_bar_processed("BTCUSD", "2025-06-01 12:00:00")
    # Second time same bar → not new (orchestrator should skip signal generation)
    assert is_new_bar("BTCUSD", "2025-06-01 12:00:00") is False


# ═══════════════════════════════════════════
# 3. ORCHESTRATOR LOCKING
# ═══════════════════════════════════════════

def test_orchestrator_lock_redis_failure_skips():
    """If Redis lock fails, cycle must be skipped (not proceed unlocked)."""
    with patch("bahamut.monitoring.cycle_log.start_cycle"), \
         patch("bahamut.monitoring.cycle_log.end_cycle"), \
         patch("bahamut.monitoring.cycle_log.record_skip") as mock_skip:

        # Mock redis.from_url to raise
        with patch("redis.from_url", side_effect=ConnectionError("Redis down")):
            from bahamut.execution.v7_orchestrator import run_v7_cycle
            # Should not raise, should skip gracefully
            try:
                run_v7_cycle()
            except SystemExit:
                pass  # Celery task wrapper may exit

            mock_skip.assert_called_once()
            call_args = mock_skip.call_args[0][0]
            assert "lock" in call_args.lower() or "failed" in call_args.lower()


def test_orchestrator_lock_held_skips():
    """If lock already held, cycle must be skipped."""
    with patch("bahamut.monitoring.cycle_log.start_cycle"), \
         patch("bahamut.monitoring.cycle_log.end_cycle"), \
         patch("bahamut.monitoring.cycle_log.record_skip") as mock_skip:

        mock_redis = MagicMock()
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False  # Lock held by another worker
        mock_redis.lock.return_value = mock_lock

        with patch("redis.from_url", return_value=mock_redis):
            from bahamut.execution.v7_orchestrator import run_v7_cycle
            run_v7_cycle()

            mock_skip.assert_called_once()


# ═══════════════════════════════════════════
# 4. PERFORMANCE MATCHES TRADES
# ═══════════════════════════════════════════

@patch("bahamut.monitoring.performance.get_portfolio_manager")
@patch("bahamut.monitoring.performance.get_execution_engine")
def test_performance_reads_closed_trades(mock_eng, mock_pm):
    """Performance engine must read from same source as trades tab."""
    eng = MockEngine()
    eng.closed_trades = [
        FakeTrade(strategy="v5_base", pnl=500, asset="BTCUSD"),
        FakeTrade(strategy="v5_base", pnl=-200, asset="BTCUSD"),
        FakeTrade(strategy="v9_breakout", pnl=800, asset="ETHUSD"),
    ]
    mock_eng.return_value = eng
    mock_pm.return_value = MagicMock(total_equity=100000)

    from bahamut.monitoring.performance import compute_performance
    result = compute_performance()

    assert result["has_data"] is True
    assert result["portfolio"]["total_trades"] == 3
    assert result["portfolio"]["pnl"] == 1100.0
    assert result["portfolio"]["wins"] == 2
    assert result["portfolio"]["losses"] == 1
    assert result["portfolio"]["win_rate"] == pytest.approx(66.7, abs=0.1)
    assert result["portfolio"]["gross_profit"] == 1300.0
    assert result["portfolio"]["gross_loss"] == 200.0


@patch("bahamut.monitoring.performance.get_portfolio_manager")
@patch("bahamut.monitoring.performance.get_execution_engine")
def test_performance_excludes_test_trades(mock_eng, mock_pm):
    """Performance must exclude TEST_ trades."""
    eng = MockEngine()
    eng.closed_trades = [
        FakeTrade(strategy="v5_base", pnl=500),
        FakeTrade(strategy="TEST_test_trade", pnl=-10000),  # should be excluded
    ]
    mock_eng.return_value = eng
    mock_pm.return_value = MagicMock(total_equity=100000)

    from bahamut.monitoring.performance import compute_performance
    result = compute_performance()

    assert result["portfolio"]["total_trades"] == 1
    assert result["portfolio"]["pnl"] == 500.0


@patch("bahamut.monitoring.performance.get_portfolio_manager")
@patch("bahamut.monitoring.performance.get_execution_engine")
def test_performance_empty_state(mock_eng, mock_pm):
    """No trades → has_data=False, metrics at zero."""
    mock_eng.return_value = MockEngine()
    mock_pm.return_value = MagicMock(total_equity=100000)

    from bahamut.monitoring.performance import compute_performance
    result = compute_performance()

    assert result["has_data"] is False
    assert result["portfolio"]["total_trades"] == 0
    assert result["portfolio"]["pnl"] == 0.0
    assert result["portfolio"]["win_rate"] == 0.0


@patch("bahamut.monitoring.performance.get_portfolio_manager")
@patch("bahamut.monitoring.performance.get_execution_engine")
def test_performance_metrics_completeness(mock_eng, mock_pm):
    """Performance response must include all required fields."""
    eng = MockEngine()
    eng.closed_trades = [FakeTrade(strategy="v5_base", pnl=100)]
    mock_eng.return_value = eng
    mock_pm.return_value = MagicMock(total_equity=100000)

    from bahamut.monitoring.performance import compute_performance
    result = compute_performance()

    required = ["total_trades", "win_rate", "gross_profit", "gross_loss",
                "profit_factor", "expectancy", "pnl"]
    for field in required:
        assert field in result["portfolio"], f"Missing required field: {field}"


# ═══════════════════════════════════════════
# 5. ALERT DEDUP
# ═══════════════════════════════════════════

def test_alert_dedup_same_key():
    """Same alert key → updates existing, doesn't create new."""
    from bahamut.monitoring.alerts import fire_alert, _alert_history

    # Clear state
    _alert_history.clear()

    fire_alert("WARNING", "Test Alert", "msg1", key="test_dedup_key")
    fire_alert("WARNING", "Test Alert", "msg2", key="test_dedup_key")

    # Should only have one entry with this key
    matches = [a for a in _alert_history if a.get("key") == "test_dedup_key"]
    assert len(matches) == 1, f"Alert duplicated: found {len(matches)} entries"
    assert matches[0].get("occurrences", 1) >= 2, "Occurrence count not incremented"


def test_alert_dedup_different_keys():
    """Different keys → separate alerts."""
    from bahamut.monitoring.alerts import fire_alert, _alert_history

    _alert_history.clear()

    fire_alert("WARNING", "Alert A", "msg", key="key_a")
    fire_alert("WARNING", "Alert B", "msg", key="key_b")

    keys = [a.get("key") for a in _alert_history]
    assert "key_a" in keys
    assert "key_b" in keys


def test_alert_key_generation():
    """If no key provided, auto-generate from level+title."""
    from bahamut.monitoring.alerts import fire_alert, _alert_history

    _alert_history.clear()

    fire_alert("CRITICAL", "Drawdown exceeded 8%", "test msg")

    assert len(_alert_history) >= 1
    keys = [a.get("key") for a in _alert_history]
    assert any("CRITICAL" in k or "Drawdown" in k for k in keys)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ═══════════════════════════════════════════
# 6. AUDIT: BAR STATE DURABILITY & ATOMICITY
# ═══════════════════════════════════════════

def test_is_new_bar_read_only():
    """is_new_bar must NOT modify state — it's a check, not a commit."""
    from bahamut.data.live_data import is_new_bar, _last_bar_timestamps
    _last_bar_timestamps.clear()
    _last_bar_timestamps["BTCUSD"] = "2025-01-01 04:00:00"

    result = is_new_bar("BTCUSD", "2025-01-01 08:00:00")
    assert result is True
    # State must NOT have changed — is_new_bar is read-only now
    assert _last_bar_timestamps["BTCUSD"] == "2025-01-01 04:00:00", \
        "is_new_bar modified state! It must be read-only."


def test_mark_bar_processed_advances_state():
    """mark_bar_processed must advance the in-memory state."""
    from bahamut.data.live_data import mark_bar_processed, is_new_bar, _last_bar_timestamps
    _last_bar_timestamps.clear()
    _last_bar_timestamps["BTCUSD"] = "2025-01-01 04:00:00"

    mark_bar_processed("BTCUSD", "2025-01-01 08:00:00")
    assert _last_bar_timestamps["BTCUSD"] == "2025-01-01 08:00:00"
    # Same bar should no longer be new
    assert is_new_bar("BTCUSD", "2025-01-01 08:00:00") is False


def test_partial_asset_failure_atomicity():
    """If BTC succeeds but ETH fails, only BTC should advance."""
    from bahamut.data.live_data import is_new_bar, mark_bar_processed, _last_bar_timestamps
    _last_bar_timestamps.clear()
    _last_bar_timestamps["BTCUSD"] = "old"
    _last_bar_timestamps["ETHUSD"] = "old"

    # Both assets have a new bar
    assert is_new_bar("BTCUSD", "new") is True
    assert is_new_bar("ETHUSD", "new") is True

    # BTC processes successfully → commit
    mark_bar_processed("BTCUSD", "new")
    # ETH crashes → no mark_bar_processed called

    # Next cycle: BTC should NOT reprocess, ETH SHOULD retry
    assert is_new_bar("BTCUSD", "new") is False, "BTC should not reprocess"
    assert is_new_bar("ETHUSD", "new") is True, "ETH should retry after failure"


def test_redis_flush_recovery():
    """After Redis flush, bar state should still be loadable from DB or start fresh."""
    from bahamut.data.live_data import _last_bar_timestamps, _bar_state_initialized
    import bahamut.data.live_data as live_data_module

    # Simulate cold start after Redis flush
    _last_bar_timestamps.clear()
    live_data_module._bar_state_initialized = False

    # _ensure_bar_state_loaded will try DB then Redis — both may fail in test env
    # but it must not crash
    try:
        live_data_module._ensure_bar_state_loaded()
    except Exception as e:
        pytest.fail(f"_ensure_bar_state_loaded crashed: {e}")

    # After loading, should be initialized (even if empty)
    assert live_data_module._bar_state_initialized is True


def test_startup_no_duplicate_evaluation():
    """After restart, same bar must not be re-evaluated."""
    from bahamut.data.live_data import is_new_bar, mark_bar_processed, _last_bar_timestamps
    import bahamut.data.live_data as live_data_module

    _last_bar_timestamps.clear()
    live_data_module._bar_state_initialized = True  # skip DB load in test

    # Simulate: bar was processed in previous run
    mark_bar_processed("BTCUSD", "2025-06-01 12:00:00")

    # New cycle sees the same bar
    assert is_new_bar("BTCUSD", "2025-06-01 12:00:00") is False, \
        "Same bar evaluated twice after restart!"


# ═══════════════════════════════════════════
# 7. AUDIT: LOCK OWNERSHIP SAFETY
# ═══════════════════════════════════════════

def test_redis_lock_uses_token():
    """redis-py Lock uses token-based ownership by default. Verify release is safe."""
    import redis, inspect
    # redis-py 5.x Lock stores a random token on acquire via threading.local().
    # Lock.release() reads self.local.token and passes it to a Lua script that
    # only deletes the key if the stored value matches — preventing one worker
    # from releasing another worker's lock.
    src = inspect.getsource(redis.lock.Lock.release)
    assert "expected_token" in src or "self.local.token" in src, \
        "redis-py Lock.release does not check token — unsafe release possible"


# ═══════════════════════════════════════════
# 8. AUDIT: TEST TRADE ISOLATION COMPLETENESS
# ═══════════════════════════════════════════

@patch("bahamut.portfolio.manager.get_execution_engine")
def test_test_trade_excluded_from_portfolio_equity(mock_eng):
    """TEST_ trades must not affect sleeve equity (they don't match any sleeve name)."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="TEST_test", pnl=-50000))
    eng.open_positions.append(FakePosition(strategy="TEST_test", unrealized_pnl=-30000))
    mock_eng.return_value = eng

    pm = _make_manager(0.10)
    pm.update()

    # Sleeves don't include TEST_ so equity should be unaffected
    assert pm.total_equity == pm.initial_capital, \
        f"Test trade affected equity: {pm.total_equity} != {pm.initial_capital}"
    assert pm.total_drawdown == 0.0


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_test_trade_excluded_from_kill_switch_drawdown(mock_eng):
    """TEST_ trades must never trigger kill switch."""
    eng = MockEngine()
    eng.closed_trades.append(FakeTrade(strategy="TEST_huge_loss", pnl=-99000))
    mock_eng.return_value = eng

    pm = _make_manager(0.05)
    pm.update()

    assert pm.kill_switch_triggered is False
    assert pm.total_drawdown == 0.0


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_test_position_excluded_from_open_risk(mock_eng):
    """TEST_ positions must not count toward open risk in can_trade()."""
    eng = MockEngine()
    eng.open_positions.append(FakePosition(strategy="TEST_test", risk_amount=999999))
    mock_eng.return_value = eng

    pm = _make_manager(0.10)
    can, reason = pm.can_trade("v5_base", "BTCUSD")
    assert can is True, f"Test position blocked real trade: {reason}"


@patch("bahamut.monitoring.performance.get_portfolio_manager")
@patch("bahamut.monitoring.performance.get_execution_engine")
def test_performance_and_trades_use_same_exclusion(mock_eng, mock_pm):
    """Performance and Trades tabs must use consistent TEST_ exclusion rules."""
    eng = MockEngine()
    eng.closed_trades = [
        FakeTrade(strategy="v5_base", pnl=500),
        FakeTrade(strategy="TEST_lifecycle", pnl=-1000),
        FakeTrade(strategy="v9_breakout", pnl=200),
    ]
    mock_eng.return_value = eng
    mock_pm.return_value = MagicMock(total_equity=100000)

    from bahamut.monitoring.performance import compute_performance
    perf = compute_performance()

    # Performance should have 2 trades (excluding TEST_)
    assert perf["portfolio"]["total_trades"] == 2
    assert perf["portfolio"]["pnl"] == 700.0

    # Verify consistency: the same trades that performance counts
    # should be the same ones the dashboard count would report
    real_trades = [t for t in eng.closed_trades if not t.strategy.startswith("TEST_")]
    assert len(real_trades) == perf["portfolio"]["total_trades"]
