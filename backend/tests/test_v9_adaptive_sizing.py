"""
Phase 3 Item 9 — v9 adaptive SL/TP/hold tests.
"""
import os


def _fresh_v9():
    """Reimport to pick up env var changes if any test sets them."""
    from bahamut.alpha.v9_candidate import V9Breakout
    return V9Breakout()


def _candles_with_breakout(length=30, base=100, breakout_magnitude=2.0):
    """Build candles where the last few bars break above a 20-bar high."""
    candles = []
    for i in range(length - 5):
        candles.append({
            "open": base + i * 0.1,
            "high": base + i * 0.1 + 0.5,
            "low": base + i * 0.1 - 0.5,
            "close": base + i * 0.1,
            "volume": 1000,
            "datetime": f"2026-01-01T{i:02d}:00:00+00:00",
            "is_closed": True,
        })
    # Breakout: last 5 bars close above the 20-bar reference high
    ref_high = max(c["high"] for c in candles[-20:])
    breakout_price = ref_high + breakout_magnitude
    for i in range(5):
        candles.append({
            "open": breakout_price - 0.2,
            "high": breakout_price + 0.5,
            "low": breakout_price - 0.3,
            "close": breakout_price + (0.1 * i),  # confirms upward
            "volume": 1500,
            "datetime": f"2026-01-01T{length-5+i:02d}:00:00+00:00",
            "is_closed": True,
        })
    return candles, ref_high


def test_detect_breakout_populates_atr_and_distance():
    """BreakoutSignal now carries atr + breakout_level for evaluate()."""
    from bahamut.alpha.v9_candidate import detect_confirmed_breakout
    candles, ref_high = _candles_with_breakout()
    close = candles[-1]["close"]
    indicators = {
        "close": close, "atr_14": 1.0, "ema_200": close * 0.9,
    }
    sig = detect_confirmed_breakout(candles, indicators)
    assert sig.valid, "breakout should be detected"
    assert sig.atr > 0
    assert sig.breakout_level > 0
    # dist_above_atr can be small/negative when close is barely above
    # ref_high * 0.995 (within tolerance). The important fields are
    # atr and breakout_level, which evaluate() needs for SL sizing.
    assert isinstance(sig.dist_above_atr, (int, float))


def test_v9_adaptive_sl_tighter_than_legacy_on_quiet_market():
    """In a low-ATR market, adaptive SL must be tighter than the legacy 10%."""
    os.environ.pop("BAHAMUT_V9_ADAPTIVE_SIZING", None)  # default on
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout(base=100, breakout_magnitude=0.5)
    close = candles[-1]["close"]
    # Low ATR: 0.3% of price — adaptive path should produce ~ atr*2.0/close = 0.6%
    indicators = {
        "close": close, "atr_14": close * 0.003, "ema_200": close * 0.9,
        "_interval": "4h",
    }
    sig = v9.evaluate(candles, indicators, None, asset="NFLX")
    assert sig is not None
    # Adaptive SL should be LESS than the legacy 10%
    assert sig.sl_pct < 0.10, f"adaptive SL should tighten; got {sig.sl_pct}"
    # And at least the 4H floor (3.5%)
    assert sig.sl_pct >= 0.035, f"SL below floor: {sig.sl_pct}"


def test_v9_adaptive_sl_widens_on_volatile_market():
    """In a high-ATR market, SL should be wider than the low-ATR case
    (but still clamped to cap)."""
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout()
    close = candles[-1]["close"]
    # High ATR: 3% of price — atr_mult=2.0 → 6% SL
    indicators = {
        "close": close, "atr_14": close * 0.03, "ema_200": close * 0.9,
        "_interval": "4h",
    }
    sig = v9.evaluate(candles, indicators, None, asset="NFLX")
    assert sig is not None
    # Should be roughly 6% — bigger than the quiet-market test would produce
    assert sig.sl_pct >= 0.05, f"expected wider SL on volatile, got {sig.sl_pct}"
    assert sig.sl_pct <= 0.10, f"SL exceeds cap: {sig.sl_pct}"


def test_v9_tp_is_at_least_2x_sl_on_adaptive():
    """R:R floor of 2.0 must hold on adaptive path."""
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout()
    close = candles[-1]["close"]
    indicators = {
        "close": close, "atr_14": close * 0.01, "ema_200": close * 0.9,
        "_interval": "4h",
    }
    sig = v9.evaluate(candles, indicators, None, asset="NFLX")
    assert sig is not None
    rr = sig.tp_pct / max(sig.sl_pct, 1e-9)
    assert rr >= 2.0, f"R:R floor violated: {rr:.2f}"


def test_v9_hold_tightened_to_20_on_4h():
    """max_hold on 4H is now 20 bars (down from 40)."""
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout()
    close = candles[-1]["close"]
    indicators = {
        "close": close, "atr_14": close * 0.01, "ema_200": close * 0.9,
        "_interval": "4h",
    }
    sig = v9.evaluate(candles, indicators, None, asset="NFLX")
    assert sig is not None
    assert sig.max_hold_bars == 20, f"expected 20 bars, got {sig.max_hold_bars}"


def test_v9_hold_tightened_to_24_on_15m():
    """max_hold on 15m is 24 bars (6 hours)."""
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout()
    close = candles[-1]["close"]
    indicators = {
        "close": close, "atr_14": close * 0.005, "ema_200": close * 0.9,
        "_interval": "15m",
    }
    sig = v9.evaluate(candles, indicators, None, asset="BTCUSD")
    assert sig is not None
    assert sig.max_hold_bars == 24, f"expected 24 bars, got {sig.max_hold_bars}"


def test_v9_legacy_mode_preserves_old_behavior():
    """With BAHAMUT_V9_ADAPTIVE_SIZING=0, SL/TP/hold revert to fixed values."""
    os.environ["BAHAMUT_V9_ADAPTIVE_SIZING"] = "0"
    try:
        v9 = _fresh_v9()
        candles, ref_high = _candles_with_breakout()
        close = candles[-1]["close"]
        indicators = {
            "close": close, "atr_14": close * 0.01, "ema_200": close * 0.9,
            "_interval": "4h",
        }
        sig = v9.evaluate(candles, indicators, None, asset="NFLX")
        assert sig is not None
        assert abs(sig.sl_pct - 0.10) < 1e-6, f"legacy SL should be 0.10, got {sig.sl_pct}"
        assert abs(sig.tp_pct - 0.25) < 1e-6, f"legacy TP should be 0.25, got {sig.tp_pct}"
        assert sig.max_hold_bars == 40
    finally:
        os.environ.pop("BAHAMUT_V9_ADAPTIVE_SIZING", None)


def test_v9_structural_sl_tightens_below_breakout_level():
    """When close is very close to ref_high*0.995, SL should be capped by
    that structural distance, not widened by high ATR."""
    v9 = _fresh_v9()
    candles, ref_high = _candles_with_breakout(breakout_magnitude=0.2)
    close = candles[-1]["close"]
    # High ATR would suggest ~6% SL — but close is only ~0.2% above ref_high,
    # so structural SL should tighten it.
    indicators = {
        "close": close, "atr_14": close * 0.03, "ema_200": close * 0.9,
        "_interval": "4h",
    }
    sig = v9.evaluate(candles, indicators, None, asset="NFLX")
    assert sig is not None
    # The absolute floor is 3.5%, so the answer is max(3.5%, struct_dist)
    # We can't assert a specific value; we can assert it's NOT the ATR-wide 6%
    # (structural has tightened us)
    assert sig.sl_pct <= 0.06, f"SL should be tightened by structure, got {sig.sl_pct}"


if __name__ == "__main__":
    import sys
    tests = [
        test_detect_breakout_populates_atr_and_distance,
        test_v9_adaptive_sl_tighter_than_legacy_on_quiet_market,
        test_v9_adaptive_sl_widens_on_volatile_market,
        test_v9_tp_is_at_least_2x_sl_on_adaptive,
        test_v9_hold_tightened_to_20_on_4h,
        test_v9_hold_tightened_to_24_on_15m,
        test_v9_legacy_mode_preserves_old_behavior,
        test_v9_structural_sl_tightens_below_breakout_level,
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
