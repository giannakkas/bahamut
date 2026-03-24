"""
Bahamut.AI — Data Health Tests

Tests the canonical data_health module that is the SINGLE SOURCE OF TRUTH
for all data freshness decisions.

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_data_health.py -v
"""
import pytest
from datetime import datetime, timezone, timedelta
from bahamut.monitoring.data_health import (
    evaluate_asset_health,
    current_4h_boundary,
    previous_4h_boundary,
    parse_bar_timestamp,
)


# ═══════════════════════════════════════════
# BOUNDARY CALCULATIONS
# ═══════════════════════════════════════════

class TestBoundaries:
    def test_boundary_at_exact_hour(self):
        now = datetime(2026, 3, 22, 20, 0, 0, tzinfo=timezone.utc)
        assert current_4h_boundary(now).hour == 20

    def test_boundary_mid_window(self):
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        assert current_4h_boundary(now).hour == 20

    def test_boundary_just_before_next(self):
        now = datetime(2026, 3, 22, 23, 59, 59, tzinfo=timezone.utc)
        assert current_4h_boundary(now).hour == 20

    def test_boundary_at_midnight(self):
        now = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)
        assert current_4h_boundary(now).hour == 0

    def test_previous_boundary(self):
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        prev = previous_4h_boundary(now)
        assert prev.hour == 16
        assert prev.day == 22

    def test_previous_boundary_at_midnight(self):
        now = datetime(2026, 3, 23, 1, 0, 0, tzinfo=timezone.utc)
        prev = previous_4h_boundary(now)
        assert prev.hour == 20
        assert prev.day == 22

    def test_previous_boundary_at_4am(self):
        now = datetime(2026, 3, 23, 5, 0, 0, tzinfo=timezone.utc)
        prev = previous_4h_boundary(now)
        assert prev.hour == 0
        assert prev.day == 23


# ═══════════════════════════════════════════
# PARSE TIMESTAMP
# ═══════════════════════════════════════════

class TestParseTimestamp:
    def test_standard_format(self):
        dt = parse_bar_timestamp("2026-03-22 16:00:00")
        assert dt is not None
        assert dt.hour == 16
        assert dt.tzinfo == timezone.utc

    def test_iso_format(self):
        dt = parse_bar_timestamp("2026-03-22T16:00:00")
        assert dt is not None

    def test_empty(self):
        assert parse_bar_timestamp("") is None
        assert parse_bar_timestamp("unknown") is None

    def test_garbage(self):
        assert parse_bar_timestamp("not a date") is None


# ═══════════════════════════════════════════
# EVALUATE ASSET HEALTH — Core Tests
# ═══════════════════════════════════════════

class TestEvaluateAssetHealth:
    """Test the canonical freshness evaluation."""

    def test_missing_no_data(self):
        """No candle data → MISSING."""
        h = evaluate_asset_health("")
        assert h["status"] == "MISSING"
        assert h["can_trade"] is False

    def test_missing_none(self):
        h = evaluate_asset_health(None)
        assert h["status"] == "MISSING"

    def test_healthy_current_bar(self):
        """Have the current (incomplete) bar → HEALTHY."""
        # now=22:30, current bar open=20:00, candle=20:00
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 20:00:00", now)
        assert h["status"] == "HEALTHY"
        assert h["can_trade"] is True
        assert h["reason"] == "have current bar"

    def test_healthy_last_completed_bar(self):
        """Have the last completed bar (not current) → HEALTHY.
        This is the normal case when TwelveData only returns completed bars.
        At 22:30, last completed bar open is 16:00."""
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 16:00:00", now)
        assert h["status"] == "HEALTHY"
        assert h["can_trade"] is True
        assert h["reason"] == "have last completed bar"

    def test_healthy_just_after_boundary(self):
        """At 20:01, last completed bar open is 16:00 → HEALTHY."""
        now = datetime(2026, 3, 22, 20, 1, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 16:00:00", now)
        assert h["status"] == "HEALTHY"
        assert h["can_trade"] is True

    def test_degraded_one_bar_behind(self):
        """At 22:30, if latest candle is 12:00 (the bar BEFORE the last completed) → DEGRADED."""
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 12:00:00", now)
        assert h["status"] == "DEGRADED"
        assert h["can_trade"] is False

    def test_stale_two_bars_behind(self):
        """At 22:30, if latest candle is 08:00 (2 bars behind) → STALE."""
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 08:00:00", now)
        assert h["status"] == "STALE"
        assert h["can_trade"] is False

    def test_stale_very_old(self):
        """Data from yesterday → STALE."""
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-21 08:00:00", now)
        assert h["status"] == "STALE"
        assert h["can_trade"] is False

    def test_midnight_boundary(self):
        """At 01:00 UTC, last completed bar open = 20:00 previous day → HEALTHY."""
        now = datetime(2026, 3, 23, 1, 0, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 20:00:00", now)
        assert h["status"] == "HEALTHY"
        assert h["can_trade"] is True

    def test_exact_boundary(self):
        """At exactly 20:00, last completed bar open=16:00 → HEALTHY."""
        now = datetime(2026, 3, 22, 20, 0, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 16:00:00", now)
        assert h["status"] == "HEALTHY"
        assert h["can_trade"] is True


# ═══════════════════════════════════════════
# CRYPTO 24/7 — No Weekend Logic
# ═══════════════════════════════════════════

class TestCrypto247:
    def test_saturday(self):
        """Saturday should work exactly like weekdays for crypto."""
        # Saturday 22:30
        now = datetime(2026, 3, 28, 22, 30, 0, tzinfo=timezone.utc)  # Saturday
        h = evaluate_asset_health("2026-03-28 20:00:00", now)
        assert h["status"] == "HEALTHY"

    def test_sunday(self):
        """Sunday should work exactly like weekdays for crypto."""
        now = datetime(2026, 3, 29, 14, 30, 0, tzinfo=timezone.utc)  # Sunday
        h = evaluate_asset_health("2026-03-29 12:00:00", now)
        assert h["status"] == "HEALTHY"


# ═══════════════════════════════════════════
# STALE DATA BLOCKS ENTRIES
# ═══════════════════════════════════════════

class TestStaleBlocksEntries:
    def test_healthy_can_trade(self):
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 20:00:00", now)
        assert h["can_trade"] is True

    def test_degraded_cannot_trade(self):
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 12:00:00", now)
        assert h["can_trade"] is False

    def test_stale_cannot_trade(self):
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        h = evaluate_asset_health("2026-03-22 04:00:00", now)
        assert h["can_trade"] is False

    def test_missing_cannot_trade(self):
        h = evaluate_asset_health("")
        assert h["can_trade"] is False


# ═══════════════════════════════════════════
# is_data_stale COMPATIBILITY
# ═══════════════════════════════════════════

class TestIsDataStaleCompat:
    """Ensure old is_data_stale function works correctly with new logic."""

    def test_stale_old_data(self):
        from bahamut.monitoring.time_utils import is_data_stale
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        assert is_data_stale("2026-03-22 04:00:00", now) is True

    def test_not_stale_fresh_data(self):
        from bahamut.monitoring.time_utils import is_data_stale
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        # last completed bar open = 16:00 → healthy
        assert is_data_stale("2026-03-22 16:00:00", now) is False

    def test_not_stale_current_bar(self):
        from bahamut.monitoring.time_utils import is_data_stale
        now = datetime(2026, 3, 22, 22, 30, 0, tzinfo=timezone.utc)
        assert is_data_stale("2026-03-22 20:00:00", now) is False

    def test_stale_empty(self):
        from bahamut.monitoring.time_utils import is_data_stale
        assert is_data_stale("") is True


# ═══════════════════════════════════════════
# TIMING INFO
# ═══════════════════════════════════════════

class TestAssetTiming:
    def test_timing_healthy_waiting(self):
        from bahamut.monitoring.time_utils import get_asset_timing, current_4h_boundary
        from datetime import datetime, timezone
        # Use the current boundary so it's always fresh
        now = datetime.now(timezone.utc)
        boundary = current_4h_boundary(now).strftime("%Y-%m-%d %H:%M:%S")
        t = get_asset_timing(boundary, boundary)
        assert t["status"] == "WAITING"
        assert t["stale"] is False
        assert t["data_health"] == "HEALTHY"

    def test_timing_new_bar_ready(self):
        from bahamut.monitoring.time_utils import get_asset_timing, current_4h_boundary
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        boundary = current_4h_boundary(now).strftime("%Y-%m-%d %H:%M:%S")
        prev = (current_4h_boundary(now) - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        t = get_asset_timing(boundary, prev)
        assert t["status"] == "NEW_BAR_READY"
        assert t["stale"] is False

    def test_timing_stale(self):
        from bahamut.monitoring.time_utils import get_asset_timing
        from datetime import datetime, timezone, timedelta
        # Something very old → always stale
        old = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        t = get_asset_timing(old, old)
        assert t["status"] == "STALE"
        assert t["stale"] is True
        assert t["can_trade"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
