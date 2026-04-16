"""
Phase 3 Item 7 — Sub-strategy identity isolation tests.
"""


def test_signal_has_substrategy_field():
    from bahamut.strategies.base import Signal
    s = Signal(strategy="v10_mean_reversion", asset="BTCUSD", direction="LONG")
    assert hasattr(s, "substrategy")
    assert s.substrategy == ""  # default empty


def test_training_position_carries_substrategy():
    from bahamut.training.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="T1", asset="BTCUSD", asset_class="crypto",
        strategy="v10_mean_reversion", direction="SHORT",
        entry_price=100.0, stop_price=105.0, tp_price=95.0,
        size=1.0, risk_amount=100.0,
        entry_time="2026-04-16T00:00:00+00:00",
        execution_platform="binance_futures", exchange_order_id="X",
        substrategy="v10_crash_short",
    )
    assert pos.substrategy == "v10_crash_short"


def test_training_trade_carries_substrategy():
    from bahamut.training.engine import TrainingTrade
    t = TrainingTrade(
        trade_id="TR1", position_id="P1", asset="BTCUSD", asset_class="crypto",
        strategy="v10_mean_reversion", direction="SHORT",
        entry_price=100.0, exit_price=99.0, stop_price=105.0, tp_price=95.0,
        size=1.0, risk_amount=100.0, pnl=1.0, pnl_pct=0.01,
        entry_time="2026-04-16T00:00:00+00:00",
        exit_time="2026-04-16T01:00:00+00:00",
        exit_reason="TP", bars_held=5,
        substrategy="v10_range_short",
    )
    assert t.substrategy == "v10_range_short"


def test_pending_signal_carries_substrategy():
    from bahamut.training.selector import PendingSignal
    p = PendingSignal(
        asset="BTCUSD", asset_class="crypto", strategy="v10_mean_reversion",
        direction="LONG", readiness_score=50, regime="RANGE",
        entry_price=100.0, sl_pct=0.02, tp_pct=0.04, max_hold_bars=10,
        reasons=[], substrategy="v10_range_long",
    )
    assert p.substrategy == "v10_range_long"


def test_v10_evaluate_tags_crash_short():
    """When detect_crash_short returns a valid signal, the substrategy
    tag must be 'v10_crash_short'."""
    from bahamut.alpha.v10_mean_reversion import V10MeanReversion, MeanReversionSignal

    # Build a fake signal with entry_type='crash_short' direct on the class
    # — we test the tagging logic by monkey-patching detect_crash_short
    # so evaluate() returns the crash path.
    strategy = V10MeanReversion()
    import bahamut.alpha.v10_mean_reversion as v10_mod

    fake_crash_sig = MeanReversionSignal(
        valid=True, direction="SHORT",
        entry_type="crash_short",
        reason="test", confidence=0.8,
    )
    original = v10_mod.detect_crash_short
    v10_mod.detect_crash_short = lambda *a, **kw: fake_crash_sig
    try:
        # Build minimal candles + indicators for evaluate
        candles = [{"close": 100 + i * 0.1, "open": 100, "high": 101, "low": 99,
                    "volume": 1000, "datetime": f"2026-01-01T{i:02d}:00:00+00:00",
                    "is_closed": True} for i in range(30)]
        indicators = {
            "close": 100.0, "ema_20": 100.5, "ema_50": 100.2,
            "ema_200": 99.8, "atr_14": 1.0, "rsi_14": 50, "adx_14": 20,
            "bollinger_upper": 102, "bollinger_mid": 100, "bollinger_lower": 98,
            "_regime": "RANGE", "_asset_class": "crypto", "_interval": "15m",
        }
        sig = strategy.evaluate(candles, indicators, None, asset="BTCUSD")
        assert sig is not None, "evaluate should return a signal"
        assert sig.substrategy == "v10_crash_short", \
            f"expected v10_crash_short, got '{sig.substrategy}'"
    finally:
        v10_mod.detect_crash_short = original


def test_v10_evaluate_tags_range_long():
    """Confirm the range_long tag when a regular LONG mean-reversion signal fires."""
    from bahamut.alpha.v10_mean_reversion import V10MeanReversion, MeanReversionSignal
    import bahamut.alpha.v10_mean_reversion as v10_mod

    fake_crash = MeanReversionSignal(valid=False)
    fake_long = MeanReversionSignal(valid=True, direction="LONG",
                                     entry_type="mean_reversion_long",
                                     reason="oversold bounce", confidence=0.7)
    fake_none = MeanReversionSignal(valid=False)
    orig_c = v10_mod.detect_crash_short
    orig_l = v10_mod.detect_mean_reversion
    orig_s = v10_mod.detect_mean_reversion_short
    v10_mod.detect_crash_short = lambda *a, **kw: fake_crash
    v10_mod.detect_mean_reversion = lambda *a, **kw: fake_long
    v10_mod.detect_mean_reversion_short = lambda *a, **kw: fake_none
    try:
        strategy = V10MeanReversion()
        candles = [{"close": 100.0, "open": 100, "high": 101, "low": 99,
                    "volume": 1000, "datetime": "2026-01-01", "is_closed": True}]
        indicators = {
            "close": 100.0, "ema_20": 100.5, "ema_50": 100.2,
            "ema_200": 99.8, "atr_14": 1.0, "rsi_14": 30, "adx_14": 20,
            "bollinger_upper": 102, "bollinger_mid": 100, "bollinger_lower": 98,
            "_regime": "RANGE", "_asset_class": "stock", "_interval": "4h",
        }
        # Use NFLX — not in any suppress list
        sig = strategy.evaluate(candles, indicators, None, asset="NFLX")
        assert sig is not None, "evaluate should return a signal"
        assert sig.substrategy == "v10_range_long", \
            f"expected v10_range_long, got '{sig.substrategy}'"
    finally:
        v10_mod.detect_crash_short = orig_c
        v10_mod.detect_mean_reversion = orig_l
        v10_mod.detect_mean_reversion_short = orig_s


def test_is_suppressed_checks_substrategy():
    """is_suppressed() must honor SUBSTRATEGY_SUPPRESS when substrategy
    is non-empty; ignore it when empty (legacy behavior)."""
    from bahamut.config_assets import is_suppressed, SUBSTRATEGY_SUPPRESS
    # Inject a test entry
    SUBSTRATEGY_SUPPRESS["v10_crash_short"] = {"TESTASSET"}
    try:
        # Blocked when substrategy is specified
        assert is_suppressed("TESTASSET", "v10_mean_reversion",
                             substrategy="v10_crash_short") is True
        # Not blocked under a different substrategy
        assert is_suppressed("TESTASSET", "v10_mean_reversion",
                             substrategy="v10_range_long") is False
        # Legacy callers that don't pass substrategy — not blocked
        # (correctly — they don't carry the discriminator)
        assert is_suppressed("TESTASSET", "v10_mean_reversion") is False
    finally:
        # Cleanup — remove test entry
        SUBSTRATEGY_SUPPRESS.pop("v10_crash_short", None)


def test_learning_context_captures_substrategy():
    from bahamut.training.learning_engine import compute_learning_context
    trade = {
        "strategy": "v10_mean_reversion", "asset": "BTCUSD",
        "asset_class": "crypto", "direction": "SHORT", "regime": "CRASH",
        "exit_reason": "TP", "pnl": 10.0, "risk_amount": 100.0,
        "bars_held": 5, "substrategy": "v10_crash_short",
    }
    ctx = compute_learning_context(trade)
    assert ctx.substrategy == "v10_crash_short"


def test_build_trust_keys_adds_substrategy_keys():
    from bahamut.training.learning_engine import LearningContext, _build_trust_keys
    ctx = LearningContext(
        strategy="v10_mean_reversion", asset="BTCUSD",
        asset_class="crypto", direction="SHORT", regime="CRASH",
        exit_reason="TP", pnl=10, r_multiple=0.5, bars_held=5,
        quick_stop=False, outcome_score=0.5,
        substrategy="v10_crash_short",
    )
    keys = _build_trust_keys(ctx)
    # Parent strategy keys present
    assert any("trust:strategy:v10_mean_reversion" in k for k in keys)
    # Substrategy keys present
    assert any("trust:substrategy:v10_crash_short" in k for k in keys)
    assert any("trust:substrategy_class:v10_crash_short:crypto" in k for k in keys)
    assert any("trust:substrategy_pattern:v10_crash_short:CRASH:crypto" in k for k in keys)


def test_build_trust_keys_no_substrategy_legacy():
    """When substrategy is empty, only parent keys — no substrategy pollution."""
    from bahamut.training.learning_engine import LearningContext, _build_trust_keys
    ctx = LearningContext(
        strategy="v5_base", asset="AAPL", asset_class="stock",
        direction="LONG", regime="TREND", exit_reason="TP",
        pnl=10, r_multiple=0.5, bars_held=5,
        quick_stop=False, outcome_score=0.5,
        substrategy="",
    )
    keys = _build_trust_keys(ctx)
    assert len(keys) == 4  # original four, no substrategy additions
    assert not any("substrategy" in k for k in keys)


def test_get_substrategy_trust_empty_safe():
    """With empty substrategy or no Redis, returns safe defaults."""
    from bahamut.training.learning_engine import get_substrategy_trust
    result = get_substrategy_trust("", "RANGE", "crypto")
    assert result["substrategy"] == ""
    assert result["trust"] == 0.5
    assert result["samples"] == 0


if __name__ == "__main__":
    import sys
    tests = [
        test_signal_has_substrategy_field,
        test_training_position_carries_substrategy,
        test_training_trade_carries_substrategy,
        test_pending_signal_carries_substrategy,
        test_v10_evaluate_tags_crash_short,
        test_v10_evaluate_tags_range_long,
        test_is_suppressed_checks_substrategy,
        test_learning_context_captures_substrategy,
        test_build_trust_keys_adds_substrategy_keys,
        test_build_trust_keys_no_substrategy_legacy,
        test_get_substrategy_trust_empty_safe,
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
