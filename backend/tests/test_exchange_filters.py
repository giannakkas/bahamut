"""
Phase 2 Item 6 — Exchange filter tests.

No network calls: we inject the fallback table directly and verify
rounding + validation logic.
"""


def _reset_and_seed():
    """Inject fallback filters into the module cache for deterministic tests."""
    from bahamut.execution import exchange_filters as ef
    ef._FILTERS = dict(ef._FALLBACK_FILTERS)
    ef._FILTERS_FETCHED_AT = 9999999999  # Very future — cache hit forever for tests


def test_precision_from_step():
    from bahamut.execution.exchange_filters import _precision_from_step
    assert _precision_from_step(0.001) == 3
    assert _precision_from_step(0.01) == 2
    assert _precision_from_step(1.0) == 0
    assert _precision_from_step(0.5) == 1
    # 1e-8 is very small — precision should be exactly 8
    assert _precision_from_step(1e-8) == 8


def test_round_qty_down_not_up():
    """Rounding must be DOWN to avoid exceeding available margin."""
    _reset_and_seed()
    from bahamut.execution.exchange_filters import round_qty
    # BTC step 0.001 — 0.1237 should round to 0.123 (not 0.124)
    assert round_qty("BTCUSDT", 0.1237) == 0.123
    # ETH step 0.001 — 0.9999 → 0.999
    assert round_qty("ETHUSDT", 0.9999) == 0.999
    # DOGE step 1 — 1234.7 → 1234
    assert round_qty("DOGEUSDT", 1234.7) == 1234.0
    # BNB step 0.01 — 5.678 → 5.67
    assert round_qty("BNBUSDT", 5.678) == 5.67


def test_round_qty_exact_multiple_unchanged():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import round_qty
    assert round_qty("BTCUSDT", 0.123) == 0.123
    assert round_qty("DOGEUSDT", 1000.0) == 1000.0


def test_validate_order_below_min_qty():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import validate_order
    # BTC minQty = 0.001 — 0.0005 is below
    valid, reason = validate_order("BTCUSDT", 0.0005, 50000)
    assert not valid
    assert "minQty" in reason


def test_validate_order_below_min_notional():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import validate_order
    # BTC minNotional = 5.0; 0.001 BTC * $1 = $0.001 — below
    valid, reason = validate_order("BTCUSDT", 0.001, 1.0)
    assert not valid
    assert "notional" in reason.lower()


def test_validate_order_healthy():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import validate_order
    # 0.01 BTC * $50k = $500 notional — well above $5 minimum
    valid, reason = validate_order("BTCUSDT", 0.01, 50000)
    assert valid, f"expected valid, got: {reason}"


def test_validate_order_not_step_multiple():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import validate_order
    # BTC stepSize 0.001; 0.0015 is not a multiple (should be 0.001 or 0.002)
    valid, reason = validate_order("BTCUSDT", 0.0015, 50000)
    assert not valid
    assert "step" in reason.lower()


def test_format_qty_canonical_adjustment_logged():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import format_qty_canonical
    s, adj = format_qty_canonical("BTCUSD", 0.12345)  # asset-side name
    # Should round down to 0.123 and format with 3 decimals
    assert s == "0.123"
    assert adj["rounded_qty"] == 0.123
    assert adj["stepSize"] == 0.001
    assert abs(adj["adjustment_delta"] - 0.00045) < 1e-9


def test_format_qty_canonical_integer_precision_for_doge():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import format_qty_canonical
    s, adj = format_qty_canonical("DOGEUSD", 1234.7)
    assert s == "1234"  # integer precision, rounded down
    assert adj["rounded_qty"] == 1234.0


def test_format_qty_canonical_below_step_is_invalid():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import format_qty_canonical
    # 0.0005 BTC < stepSize 0.001 → rounds to 0 → INVALID_BELOW_STEP
    s, adj = format_qty_canonical("BTCUSD", 0.0005)
    assert s == "INVALID_BELOW_STEP"
    assert adj["rounded_qty"] == 0.0
    assert "error" in adj


def test_unknown_symbol_falls_back_to_default():
    _reset_and_seed()
    from bahamut.execution.exchange_filters import get_filters, format_qty_canonical
    f = get_filters("NONEXISTENTXYZ")
    assert f["source"] == "fallback_default"
    # Should still be usable — 2 decimal default
    s, adj = format_qty_canonical("NONEXISTENT", 1.2345)
    # _to_symbol appends USDT → 'NONEXISTENTUSDT' which is unknown → fallback default
    # Source could be either the unknown-symbol default or the exchange_info cache
    assert adj["source"] in ("fallback_default", "binance_exchange_info")


if __name__ == "__main__":
    import sys
    tests = [
        test_precision_from_step,
        test_round_qty_down_not_up,
        test_round_qty_exact_multiple_unchanged,
        test_validate_order_below_min_qty,
        test_validate_order_below_min_notional,
        test_validate_order_healthy,
        test_validate_order_not_step_multiple,
        test_format_qty_canonical_adjustment_logged,
        test_format_qty_canonical_integer_precision_for_doge,
        test_format_qty_canonical_below_step_is_invalid,
        test_unknown_symbol_falls_back_to_default,
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
