"""
Phase 1 Item 1 — Closed-candle enforcement invariant tests.
"""


def _approx(a, b, tol=0.01):
    return abs(float(a) - float(b)) < tol


def _make_candles(n=40, base_price=100.0, forming_last=False):
    candles = []
    for i in range(n):
        is_closed = True
        if forming_last and i == n - 1:
            is_closed = False
        candles.append({
            "open": base_price + i,
            "high": base_price + i + 0.5,
            "low": base_price + i - 0.5,
            "close": base_price + i + 0.2,
            "volume": 1000.0,
            "datetime": f"2026-01-01T{i:02d}:00:00+00:00",
            "open_time": 1700000000 + i * 900,
            "close_time": 1700000000 + (i + 1) * 900,
            "is_closed": is_closed,
            "source": "test",
        })
    return candles


def test_forming_candle_dropped_in_binance_indicators():
    from bahamut.data.binance_data import compute_indicators
    candles = _make_candles(40, forming_last=True)
    result = compute_indicators(candles)
    assert result, "indicators should still be computed from the 39 closed bars"
    # Last closed bar close = 100 + 38 + 0.2 = 138.2
    assert _approx(result["close"], 138.2), \
        f"expected 138.2 (last closed bar), got {result['close']}"


def test_closed_last_candle_used_normally():
    from bahamut.data.binance_data import compute_indicators
    candles = _make_candles(40, forming_last=False)
    result = compute_indicators(candles)
    assert result
    assert _approx(result["close"], 139.2)


def test_legacy_candles_without_is_closed_assumed_closed():
    from bahamut.data.binance_data import compute_indicators
    candles = _make_candles(40, forming_last=False)
    for c in candles:
        c.pop("is_closed", None)
    result = compute_indicators(candles)
    assert result
    assert _approx(result["close"], 139.2), "legacy candles should be used as-is"


def test_features_indicators_drops_forming():
    from bahamut.features.indicators import compute_indicators
    candles = _make_candles(40, forming_last=True)
    result = compute_indicators(candles)
    assert result
    assert _approx(float(result["close"]), 138.2)


def test_features_indicators_closed_last_used():
    from bahamut.features.indicators import compute_indicators
    candles = _make_candles(40, forming_last=False)
    result = compute_indicators(candles)
    assert result
    assert _approx(float(result["close"]), 139.2)


def test_last_candle_closed_state_helper_exists():
    from bahamut.data.binance_data import last_candle_closed_state
    state = last_candle_closed_state()
    assert isinstance(state, dict)


if __name__ == "__main__":
    import sys
    tests = [
        test_forming_candle_dropped_in_binance_indicators,
        test_closed_last_candle_used_normally,
        test_legacy_candles_without_is_closed_assumed_closed,
        test_features_indicators_drops_forming,
        test_features_indicators_closed_last_used,
        test_last_candle_closed_state_helper_exists,
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
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
