"""
Bahamut Data Module Tests

Run: python -m bahamut.tests.test_data
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))


def test_fetch_btc():
    """BTC candles should always return data (live or synthetic fallback)."""
    from bahamut.data.live_data import fetch_candles
    candles = fetch_candles("BTCUSD")
    assert len(candles) > 50, f"Too few BTC candles: {len(candles)}"
    last = candles[-1]
    assert last.get("close", 0) > 1000, f"BTC close too low: {last.get('close')}"
    assert last.get("datetime"), "Missing datetime on last candle"
    print(f"  ✓ BTC: {len(candles)} candles, last=${last['close']:,.0f} ({last['datetime']})")


def test_fetch_eth():
    """ETH candles should always return data (live or synthetic fallback)."""
    from bahamut.data.live_data import fetch_candles
    candles = fetch_candles("ETHUSD")
    assert len(candles) > 50, f"Too few ETH candles: {len(candles)}"
    last = candles[-1]
    assert last.get("close", 0) > 100, f"ETH close too low: {last.get('close')}"
    assert last.get("datetime"), "Missing datetime on last candle"
    print(f"  ✓ ETH: {len(candles)} candles, last=${last['close']:,.0f} ({last['datetime']})")


def test_validation_good():
    """Properly formed candles should pass validation."""
    from bahamut.data.live_data import validate_candles
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    candles = []
    for i in range(100):
        t = now - timedelta(hours=4 * (100 - i))
        candles.append({
            "datetime": t.strftime("%Y-%m-%d %H:%M:%S"),
            "open": 80000 + i * 10,
            "high": 80100 + i * 10,
            "low": 79900 + i * 10,
            "close": 80050 + i * 10,
            "volume": 1000,
        })

    valid, reason = validate_candles(candles)
    assert valid, f"Should be valid: {reason}"
    print("  ✓ Valid candles pass validation")


def test_validation_empty():
    from bahamut.data.live_data import validate_candles
    valid, reason = validate_candles([])
    assert not valid
    print("  ✓ Empty candles rejected")


def test_validation_too_few():
    from bahamut.data.live_data import validate_candles
    valid, reason = validate_candles([{"datetime": "2025-01-01 00:00:00", "close": 100}] * 10)
    assert not valid
    assert "too few" in reason
    print("  ✓ Too few candles rejected")


def test_validation_bad_order():
    from bahamut.data.live_data import validate_candles
    candles = [
        {"datetime": f"2025-01-{i:02d} 00:00:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
        for i in range(1, 60)
    ]
    # Swap two
    candles[30], candles[31] = candles[31], candles[30]
    valid, reason = validate_candles(candles)
    assert not valid
    assert "not increasing" in reason
    print("  ✓ Out-of-order timestamps rejected")


def test_new_bar_detection():
    """Same timestamp returns False, new timestamp returns True."""
    from bahamut.data.live_data import is_new_bar, mark_bar_processed, _last_bar_timestamps
    _last_bar_timestamps.clear()

    assert is_new_bar("TEST", "2025-03-21 20:00") is True, "First bar should be new"
    mark_bar_processed("TEST", "2025-03-21 20:00")
    assert is_new_bar("TEST", "2025-03-21 20:00") is False, "Same bar should not be new"
    assert is_new_bar("TEST", "2025-03-22 00:00") is True, "Different bar should be new"
    print("  ✓ New bar detection works")


def test_data_source():
    """Should report SYNTHETIC when no API key configured."""
    from bahamut.data.live_data import get_data_source
    src = get_data_source()
    # Without TWELVE_DATA_KEY it should be SYNTHETIC
    if not os.environ.get("TWELVE_DATA_KEY"):
        assert src == "SYNTHETIC"
        print("  ✓ Data source = SYNTHETIC (no API key)")
    else:
        assert src == "LIVE"
        print("  ✓ Data source = LIVE (API key found)")


def test_full_cycle():
    """Run a full orchestrator cycle and verify it completes."""
    import bahamut.execution.engine as ee
    import bahamut.portfolio.manager as pm_mod
    from bahamut.data.live_data import _last_bar_timestamps
    ee._engine = None; pm_mod._manager = None
    _last_bar_timestamps.clear()

    from bahamut.monitoring.cycle_log import get_last_cycle

    result = run_v7_cycle_sync()
    assert result.get("status") == "SUCCESS", f"Cycle failed: {result}"

    lc = get_last_cycle()
    assert lc.get("status") == "SUCCESS"
    assert len(lc.get("assets", [])) >= 1, "Should have at least 1 asset"

    for a in lc.get("assets", []):
        assert a.get("asset"), "Missing asset name"
        assert a.get("regime"), "Missing regime"

    print(f"  ✓ Full cycle: {lc.get('duration_ms')}ms, {len(lc['assets'])} assets evaluated")


if __name__ == "__main__":
    print("=" * 60)
    print("  BAHAMUT DATA MODULE TESTS")
    print("=" * 60)

    tests = [
        test_fetch_btc,
        test_fetch_eth,
        test_validation_good,
        test_validation_empty,
        test_validation_too_few,
        test_validation_bad_order,
        test_new_bar_detection,
        test_data_source,
        test_full_cycle,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1

    print(f"\n  {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
    print("  ALL TESTS PASSED ✓")
