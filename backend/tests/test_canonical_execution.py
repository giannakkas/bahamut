"""
Phase 2 Item 4 — Canonical ExecutionResult tests.
"""


def test_canonical_from_binance_filled():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle, FillStatus
    raw = {
        "order_id": "12345",
        "fill_price": 100.0,
        "fill_qty": 0.5,
        "status": "FILLED",
    }
    r = ExecutionResult.from_binance_futures(
        asset="BTCUSD", direction="LONG", submitted_qty=0.5,
        raw=raw, reference_price=99.5,
    )
    assert r.platform == "binance_futures"
    assert r.order_id == "12345"
    assert r.lifecycle == OrderLifecycle.FILLED.value
    assert r.fill_status == FillStatus.FILLED.value
    assert r.filled_qty == 0.5
    assert r.remaining_qty == 0.0
    assert r.avg_fill_price == 100.0
    assert abs(r.slippage_abs - 0.5) < 0.001
    assert r.slippage_pct > 0
    assert r.is_success()
    assert r.is_broker_backed()


def test_canonical_from_binance_error():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle, FillStatus
    raw = {"error": "margin_insufficient"}
    r = ExecutionResult.from_binance_futures(
        asset="BTCUSD", direction="LONG", submitted_qty=1.0,
        raw=raw, reference_price=100.0,
    )
    assert r.lifecycle == OrderLifecycle.ERROR.value
    assert r.fill_status == FillStatus.UNFILLED.value
    assert r.filled_qty == 0.0
    assert "margin_insufficient" in r.error
    assert not r.is_success()


def test_canonical_from_alpaca_filled():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle
    raw = {
        "order_id": "abc-def",
        "fill_price": 150.0,
        "fill_qty": 10,
        "status": "filled",
    }
    r = ExecutionResult.from_alpaca(
        asset="AAPL", direction="LONG", submitted_qty=10,
        raw=raw, reference_price=150.0,
    )
    assert r.platform == "alpaca"
    assert r.lifecycle == OrderLifecycle.FILLED.value
    assert r.order_id == "abc-def"
    assert r.is_success()


def test_canonical_internal_sim_is_explicit():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle
    r = ExecutionResult.internal_sim(asset="BTCUSD", direction="LONG", qty=0.1)
    assert r.platform == "internal"
    assert r.lifecycle == OrderLifecycle.INTERNAL.value
    assert not r.is_success()
    assert not r.is_broker_backed()


def test_canonical_as_dict_has_legacy_keys():
    """Existing callers read platform/order_id/fill_price/fill_qty/status — must remain."""
    from bahamut.execution.canonical import ExecutionResult
    raw = {"order_id": "X", "fill_price": 10, "fill_qty": 1, "status": "FILLED"}
    r = ExecutionResult.from_binance_futures("BTCUSD", "LONG", 1, raw, 10)
    d = r.as_dict()
    for key in ("platform", "order_id", "fill_price", "fill_qty", "status"):
        assert key in d, f"legacy key {key} missing"
    # New canonical keys also present
    for key in ("lifecycle", "fill_status", "submitted_at",
                "avg_fill_price", "reference_price",
                "slippage_abs", "slippage_pct", "commission"):
        assert key in d, f"canonical key {key} missing"


def test_canonical_partial_fill():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle, FillStatus
    raw = {
        "order_id": "99",
        "fill_price": 100.0,
        "fill_qty": 0.3,
        "status": "PARTIALLY_FILLED",
    }
    r = ExecutionResult.from_binance_futures(
        asset="BTCUSD", direction="LONG", submitted_qty=1.0,
        raw=raw, reference_price=100.0,
    )
    assert r.lifecycle == OrderLifecycle.PARTIAL.value
    assert r.fill_status == FillStatus.PARTIAL.value
    assert r.filled_qty == 0.3
    assert abs(r.remaining_qty - 0.7) < 0.001


def test_canonical_error_constructor():
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle
    r = ExecutionResult.error("binance_futures", "BTCUSD", "LONG", 1.0, "timeout")
    assert r.lifecycle == OrderLifecycle.ERROR.value
    assert "timeout" in r.error
    assert not r.is_success()


def test_legacy_status_string_mapping():
    """_legacy_status() must map canonical lifecycle to legacy strings
    that existing engine code still reads (e.g. 'error', 'filled', 'internal')."""
    from bahamut.execution.canonical import ExecutionResult, OrderLifecycle
    mapping_cases = [
        (OrderLifecycle.FILLED.value, "filled"),
        (OrderLifecycle.ERROR.value, "error"),
        (OrderLifecycle.INTERNAL.value, "internal"),
        (OrderLifecycle.PARTIAL.value, "partial"),
        (OrderLifecycle.ACCEPTED.value, "submitted"),
    ]
    for lifecycle, expected_legacy in mapping_cases:
        r = ExecutionResult(platform="test", lifecycle=lifecycle)
        assert r._legacy_status() == expected_legacy, \
            f"{lifecycle} should map to '{expected_legacy}', got '{r._legacy_status()}'"


if __name__ == "__main__":
    import sys
    tests = [
        test_canonical_from_binance_filled,
        test_canonical_from_binance_error,
        test_canonical_from_alpaca_filled,
        test_canonical_internal_sim_is_explicit,
        test_canonical_as_dict_has_legacy_keys,
        test_canonical_partial_fill,
        test_canonical_error_constructor,
        test_legacy_status_string_mapping,
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
