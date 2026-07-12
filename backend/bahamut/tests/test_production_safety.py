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





# ═══════════════════════════════════════════
# 4. PERFORMANCE MATCHES TRADES
# ═══════════════════════════════════════════









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







