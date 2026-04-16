"""
Phase 1 Item 3 — Regime detection cleanup tests.
"""
import numpy as np


def _synth_candles(n, start=100.0, slope=0.0, noise=0.0, seed=42):
    """Build synthetic closes with a linear drift so EMA slope is predictable."""
    rng = np.random.default_rng(seed)
    closes = []
    for i in range(n):
        c = start + slope * i + rng.normal(0, noise)
        closes.append(max(c, 0.01))
    candles = []
    for i, c in enumerate(closes):
        candles.append({
            "open": c * 0.999,
            "high": c * 1.002,
            "low": c * 0.998,
            "close": c,
            "volume": 1000.0,
            "datetime": f"2026-01-01T{i:03d}",
            "is_closed": True,
            "source": "test",
        })
    return candles


def _ind_from_candles(candles):
    from bahamut.features.indicators import compute_indicators
    return compute_indicators(candles)


def test_regime_result_has_structural_and_effective():
    from bahamut.regime.v8_detector import detect_regime, RegimeResult
    candles = _synth_candles(220, start=100, slope=0.1, noise=0.3)
    ind = _ind_from_candles(candles)
    result = detect_regime(ind, candles)
    assert isinstance(result, RegimeResult)
    assert result.structural_regime in ("TREND", "RANGE", "CRASH")
    assert result.effective_regime == result.structural_regime  # no overlay from detector
    assert result.sentiment_overlay == ""
    assert result.override_applied == ""
    # Legacy aliases must match canonical fields
    assert result.regime == result.structural_regime
    assert result.confidence == result.regime_confidence


def test_ema_slope_uses_true_ema_series():
    """Slope must reflect actual EMA change, not mean-of-closes. On a strong
    uptrend it should be positive; on a strong downtrend negative."""
    from bahamut.regime.v8_detector import detect_regime
    up = _synth_candles(220, start=100, slope=0.3, noise=0.1)
    down = _synth_candles(220, start=100, slope=-0.3, noise=0.1)
    up_ind = _ind_from_candles(up)
    down_ind = _ind_from_candles(down)

    r_up = detect_regime(up_ind, up)
    r_down = detect_regime(down_ind, down)
    assert r_up.features["ema50_slope"] > 0.05, f"expected +slope, got {r_up.features['ema50_slope']}"
    assert r_down.features["ema50_slope"] < -0.05, f"expected -slope, got {r_down.features['ema50_slope']}"
    assert r_up.features["ema50_slope_method"] == "true_ema_series"


def test_ema_slope_insufficient_history_flagged():
    """With < 60 candles we cannot build a valid EMA50 slope."""
    from bahamut.regime.v8_detector import detect_regime
    short = _synth_candles(40, start=100, slope=0.1)
    ind = _ind_from_candles(short)
    result = detect_regime(ind, short)
    assert result.features["ema50_slope"] == 0.0
    assert result.features["ema50_slope_method"] == "insufficient_history"


def test_detector_does_not_apply_sentiment_overlay():
    """The detector must never mutate regime based on anything other than
    structural features. Sentiment is a caller concern."""
    from bahamut.regime.v8_detector import detect_regime
    candles = _synth_candles(220, start=100, slope=0.2, noise=0.2)
    ind = _ind_from_candles(candles)
    result = detect_regime(ind, candles)
    assert result.sentiment_overlay == ""
    assert result.override_applied == ""


def test_insufficient_data_returns_range_safely():
    from bahamut.regime.v8_detector import detect_regime
    ind = {"close": 0, "ema_50": 0, "ema_200": 0}  # missing data
    result = detect_regime(ind, [])
    assert result.structural_regime == "RANGE"
    assert result.regime_confidence == 0.3


if __name__ == "__main__":
    import sys
    tests = [
        test_regime_result_has_structural_and_effective,
        test_ema_slope_uses_true_ema_series,
        test_ema_slope_insufficient_history_flagged,
        test_detector_does_not_apply_sentiment_overlay,
        test_insufficient_data_returns_range_safely,
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
