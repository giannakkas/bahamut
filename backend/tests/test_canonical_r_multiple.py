"""
Phase 5 Item 13 — Canonical R-multiple tests.
Verifies that R is computed from pnl/risk_amount (not pnl_pct/0.03).
"""


def test_r_from_real_risk():
    """R = pnl / risk_amount when risk_amount > 0."""
    pnl = 150.0
    risk = 100.0
    r = pnl / risk if risk > 0 else 0
    assert abs(r - 1.5) < 1e-6


def test_r_fallback_when_no_risk():
    """Legacy fallback: R = pnl_pct / 0.03 when risk_amount is 0."""
    pnl_pct = 0.06  # 6%
    risk = 0
    r = pnl_pct / 0.03 if risk <= 0 else 0
    assert abs(r - 2.0) < 1e-6


def test_r_negative():
    """Negative PnL → negative R."""
    pnl = -75.0
    risk = 100.0
    r = pnl / risk
    assert abs(r - (-0.75)) < 1e-6


def test_learning_engine_r_matches():
    """compute_learning_context uses pnl/risk_amount, not pnl_pct/0.03."""
    from bahamut.trading.learning_engine import compute_learning_context
    trade = {
        "strategy": "v9_breakout", "asset": "AAPL", "asset_class": "stock",
        "direction": "LONG", "regime": "TREND", "exit_reason": "TP",
        "pnl": 200.0, "risk_amount": 100.0, "bars_held": 10,
    }
    ctx = compute_learning_context(trade)
    assert abs(ctx.r_multiple - 2.0) < 1e-4, f"expected 2.0, got {ctx.r_multiple}"


def test_learning_engine_r_zero_risk():
    """When risk_amount=0, r_multiple should be 0 (not crash)."""
    from bahamut.trading.learning_engine import compute_learning_context
    trade = {
        "strategy": "v9_breakout", "asset": "AAPL", "asset_class": "stock",
        "direction": "LONG", "regime": "TREND", "exit_reason": "SL",
        "pnl": -50.0, "risk_amount": 0, "bars_held": 3,
    }
    ctx = compute_learning_context(trade)
    assert ctx.r_multiple == 0.0


if __name__ == "__main__":
    import sys
    tests = [
        test_r_from_real_risk,
        test_r_fallback_when_no_risk,
        test_r_negative,
        test_learning_engine_r_matches,
        test_learning_engine_r_zero_risk,
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
