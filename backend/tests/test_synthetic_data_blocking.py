"""
Phase 4 Item 12 — Synthetic data blocking + data_mode propagation tests.
"""
import os


def test_tag_candles_stamps_data_mode():
    """_tag_candles adds _data_mode to every candle."""
    from bahamut.data.live_data import _tag_candles, DATA_MODE_LIVE
    candles = [{"close": 100, "open": 99}, {"close": 101, "open": 100}]
    tagged = _tag_candles(candles, DATA_MODE_LIVE)
    for c in tagged:
        assert c["_data_mode"] == "live"


def test_data_mode_constants():
    """All three data modes are defined."""
    from bahamut.data.live_data import (
        DATA_MODE_LIVE, DATA_MODE_STALE_CACHE, DATA_MODE_SYNTHETIC_DEV,
    )
    assert DATA_MODE_LIVE == "live"
    assert DATA_MODE_STALE_CACHE == "stale_cache"
    assert DATA_MODE_SYNTHETIC_DEV == "synthetic_dev"


def test_block_synthetic_default_enabled():
    """BAHAMUT_BLOCK_SYNTHETIC defaults to ON (production safe)."""
    # The module reads env at import. If the var is unset, BLOCK_SYNTHETIC=True.
    # If already imported with BLOCK_SYNTHETIC=0 set, skip.
    saved = os.environ.get("BAHAMUT_BLOCK_SYNTHETIC")
    if saved == "0":
        # Test env already has opt-out — skip
        return
    from bahamut.data.live_data import BLOCK_SYNTHETIC
    assert BLOCK_SYNTHETIC is True, "synthetic should be BLOCKED by default"


def test_training_position_has_data_mode_field():
    from bahamut.training.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="T1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0,
        entry_time="2026-04-16T00:00:00+00:00",
        execution_platform="binance_futures", exchange_order_id="X",
    )
    assert hasattr(pos, "data_mode")
    assert pos.data_mode == "live"  # default


def test_training_position_data_mode_can_be_synthetic():
    from bahamut.training.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="T1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0,
        entry_time="2026-04-16T00:00:00+00:00",
        execution_platform="binance_futures", exchange_order_id="X",
        data_mode="synthetic_dev",
    )
    assert pos.data_mode == "synthetic_dev"


def test_training_trade_has_data_mode_field():
    from bahamut.training.engine import TrainingTrade
    t = TrainingTrade(
        trade_id="TR1", position_id="P1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, exit_price=105.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, pnl=5.0, pnl_pct=0.05,
        entry_time="2026-04-16T00:00:00+00:00",
        exit_time="2026-04-16T04:00:00+00:00",
        exit_reason="TP", bars_held=5,
    )
    assert hasattr(t, "data_mode")
    assert t.data_mode == "live"


def test_pending_signal_has_data_mode_field():
    from bahamut.training.selector import PendingSignal
    p = PendingSignal(
        asset="BTCUSD", asset_class="crypto", strategy="v9_breakout",
        direction="LONG", readiness_score=50, regime="TREND",
        entry_price=100.0, sl_pct=0.02, tp_pct=0.04, max_hold_bars=20,
        reasons=[], data_mode="stale_cache",
    )
    assert p.data_mode == "stale_cache"


def test_tag_candles_synthetic_all_marked():
    from bahamut.data.live_data import _tag_candles, DATA_MODE_SYNTHETIC_DEV
    candles = [{"close": 100} for _ in range(30)]
    tagged = _tag_candles(candles, DATA_MODE_SYNTHETIC_DEV)
    assert all(c["_data_mode"] == "synthetic_dev" for c in tagged)


def test_data_mode_consensus_from_indicators():
    """Simulate the orchestrator's consensus logic."""
    # Mix of modes in last 5 candles — synthetic takes precedence
    candles = (
        [{"_data_mode": "live"}] * 3
        + [{"_data_mode": "synthetic_dev"}]
        + [{"_data_mode": "live"}]
    )
    modes = {c.get("_data_mode", "live") for c in candles[-5:]}
    if "synthetic_dev" in modes:
        consensus = "synthetic_dev"
    elif "stale_cache" in modes:
        consensus = "stale_cache"
    else:
        consensus = "live"
    assert consensus == "synthetic_dev"

    # All live
    candles = [{"_data_mode": "live"}] * 5
    modes = {c.get("_data_mode", "live") for c in candles[-5:]}
    consensus = (
        "synthetic_dev" if "synthetic_dev" in modes
        else ("stale_cache" if "stale_cache" in modes else "live")
    )
    assert consensus == "live"

    # Stale + live
    candles = [{"_data_mode": "live"}] * 3 + [{"_data_mode": "stale_cache"}] * 2
    modes = {c.get("_data_mode", "live") for c in candles[-5:]}
    consensus = (
        "synthetic_dev" if "synthetic_dev" in modes
        else ("stale_cache" if "stale_cache" in modes else "live")
    )
    assert consensus == "stale_cache"


def test_open_training_position_signature_accepts_data_mode():
    """The function signature accepts data_mode keyword."""
    import inspect
    from bahamut.training.engine import open_training_position
    sig = inspect.signature(open_training_position)
    assert "data_mode" in sig.parameters
    assert sig.parameters["data_mode"].default == "live"


if __name__ == "__main__":
    import sys
    tests = [
        test_tag_candles_stamps_data_mode,
        test_data_mode_constants,
        test_block_synthetic_default_enabled,
        test_training_position_has_data_mode_field,
        test_training_position_data_mode_can_be_synthetic,
        test_training_trade_has_data_mode_field,
        test_pending_signal_has_data_mode_field,
        test_tag_candles_synthetic_all_marked,
        test_data_mode_consensus_from_indicators,
        test_open_training_position_signature_accepts_data_mode,
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
