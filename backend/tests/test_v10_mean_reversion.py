"""
Tests for v10_mean_reversion strategy.

Covers:
  1. Oversold + bounce in RANGE → should trigger
  2. TREND regime → should NOT trigger
  3. Weak signal (RSI not oversold) → should NOT trigger
  4. No bounce confirmation → should NOT trigger
  5. Full integration: V10MeanReversion.evaluate() returns Signal
  6. Candidate scorer returns valid scores
  7. Dynamic SL/TP sanity checks
"""
import pytest
import numpy as np
from bahamut.alpha.v10_mean_reversion import (
    V10MeanReversion,
    detect_mean_reversion,
    MeanReversionSignal,
    score_mean_reversion,
)


# ═══════════════════════════════════════════════════════
# HELPERS — build realistic candle + indicator data
# ═══════════════════════════════════════════════════════

def _make_candles(n: int, base_price: float = 100.0, trend: float = 0.0,
                  dip_last: float = 0.0, bounce_last: bool = False) -> list:
    """Generate n candles. Last candle can dip and/or bounce."""
    candles = []
    price = base_price
    for i in range(n):
        price += trend
        noise = np.random.uniform(-0.5, 0.5)
        o = price + noise
        h = o + abs(noise) + 0.5
        l = o - abs(noise) - 0.5
        c = o + noise * 0.3
        candles.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000 + i * 10, "datetime": f"2026-03-{i+1:02d}T00:00:00"})

    # Dip the last candle
    if dip_last > 0:
        last = candles[-1]
        dip_price = base_price * (1 - dip_last)
        prev = candles[-2]
        if bounce_last:
            # Bounce: close higher than prev close, but still below mean
            last["low"] = dip_price * 0.99
            last["close"] = prev["close"] + 0.1  # Slightly above prev close
            last["open"] = dip_price
            last["high"] = last["close"] + 0.3
        else:
            last["close"] = dip_price
            last["low"] = dip_price * 0.99
            last["open"] = dip_price + 1
            last["high"] = dip_price + 1.5

    return candles


def _make_indicators(close: float, ema_20: float, bb_lower: float, bb_mid: float,
                     bb_upper: float, rsi: float, atr: float, regime: str = "RANGE") -> dict:
    """Build a full indicators dict."""
    return {
        "close": close,
        "open": close + 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "ema_20": ema_20,
        "ema_50": ema_20 * 1.01,
        "ema_200": ema_20 * 1.02,
        "bollinger_lower": bb_lower,
        "bollinger_mid": bb_mid,
        "bollinger_upper": bb_upper,
        "rsi_14": rsi,
        "atr_14": atr,
        "_regime": regime,
    }


# ═══════════════════════════════════════════════════════
# TEST 1: Oversold + bounce in RANGE → SHOULD TRIGGER
# ═══════════════════════════════════════════════════════

def test_oversold_bounce_triggers():
    """Perfect mean reversion setup: RANGE, stretched below EMA, RSI oversold, bounce."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1,       # 2.9% below EMA20
        ema_20=100.0,
        bb_lower=97.0,    # At lower band
        bb_mid=100.0,
        bb_upper=103.0,
        rsi=28.0,         # Oversold
        atr=1.5,
    )
    # Make prev candle close lower than current for bounce confirmation
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    sig = detect_mean_reversion(candles, indicators, regime="RANGE")

    assert sig.valid, f"Expected trigger, got: {sig.reason}"
    assert sig.direction == "LONG"
    assert sig.confidence >= 0.5
    assert sig.distance_from_mean_pct > 2.0
    assert "mean reversion" in sig.reason.lower()


# ═══════════════════════════════════════════════════════
# TEST 2: TREND regime → should NOT trigger
# ═══════════════════════════════════════════════════════

def test_trend_regime_blocks():
    """Same oversold conditions but in TREND regime → must not fire."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=28.0, atr=1.5,
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    sig = detect_mean_reversion(candles, indicators, regime="TREND")

    assert not sig.valid
    assert "wrong regime" in sig.reason.lower()


# ═══════════════════════════════════════════════════════
# TEST 3: RSI not oversold → should NOT trigger
# ═══════════════════════════════════════════════════════

def test_rsi_not_oversold_blocks():
    """RANGE regime, stretched below EMA, but RSI at 55 → too strong to mean revert."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=55.0, atr=1.5,  # RSI too high
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    sig = detect_mean_reversion(candles, indicators, regime="RANGE")

    assert not sig.valid
    assert "rsi" in sig.reason.lower()


# ═══════════════════════════════════════════════════════
# TEST 4: No bounce → should NOT trigger
# ═══════════════════════════════════════════════════════

def test_no_bounce_blocks():
    """Oversold in RANGE but still falling — no bounce confirmation."""
    candles = _make_candles(30, base_price=100.0)
    indicators = _make_indicators(
        close=96.5, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=28.0, atr=1.5,
    )
    # Current close LOWER than prev — no bounce
    candles[-2]["close"] = 97.0
    candles[-1]["close"] = 96.5  # Below prev AND below band

    sig = detect_mean_reversion(candles, indicators, regime="RANGE")

    assert not sig.valid
    assert "bounce" in sig.reason.lower()


# ═══════════════════════════════════════════════════════
# TEST 5: V10MeanReversion.evaluate() integration
# ═══════════════════════════════════════════════════════

def test_strategy_evaluate_returns_signal():
    """Full integration: strategy class returns proper Signal object."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=28.0, atr=1.5, regime="RANGE",
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    v10 = V10MeanReversion()
    signal = v10.evaluate(candles, indicators, asset="BTCUSD")

    assert signal is not None, "Expected Signal, got None"
    assert signal.strategy == "v10_mean_reversion"
    assert signal.asset == "BTCUSD"
    assert signal.direction == "LONG"
    assert 0 < signal.sl_pct <= 0.08, f"SL {signal.sl_pct} out of bounds"
    assert 0.02 <= signal.tp_pct <= 0.08, f"TP {signal.tp_pct} out of bounds"
    assert signal.max_hold_bars == 10
    assert signal.quality >= 0.5


# ═══════════════════════════════════════════════════════
# TEST 6: Candidate scorer returns valid score
# ═══════════════════════════════════════════════════════

def test_candidate_scorer():
    """score_mean_reversion returns a Candidate with score 0-100."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=28.0, atr=1.5,
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    c = score_mean_reversion("BTCUSD", "crypto", candles, indicators, regime="RANGE")

    assert c is not None
    assert c.strategy == "v10_mean_reversion"
    assert 0 <= c.score <= 100
    assert c.score >= 70, f"Expected high score for perfect setup, got {c.score}"
    assert c.direction == "LONG"
    assert "ema_distance_pct" in c.indicators


# ═══════════════════════════════════════════════════════
# TEST 7: Scorer returns low score for non-RANGE
# ═══════════════════════════════════════════════════════

def test_candidate_scorer_low_in_trend():
    """Scorer should return low score when regime is TREND (no regime points)."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=28.0, atr=1.5,
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    c = score_mean_reversion("BTCUSD", "crypto", candles, indicators, regime="TREND")

    assert c is not None
    assert c.score < 80, f"Score should be lower in TREND, got {c.score}"
    assert c.score_breakdown["regime"] == 0


# ═══════════════════════════════════════════════════════
# TEST 8: CRASH regime blocks strategy
# ═══════════════════════════════════════════════════════

def test_crash_regime_blocks():
    """CRASH regime must not fire — even if oversold."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=22.0, atr=1.5,
    )
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    sig = detect_mean_reversion(candles, indicators, regime="CRASH")
    assert not sig.valid
    assert "wrong regime" in sig.reason.lower()


# ═══════════════════════════════════════════════════════
# TEST 9: RSI cross-up from below 30 triggers
# ═══════════════════════════════════════════════════════

def test_rsi_cross_up_triggers():
    """RSI at 32 (above threshold 35) but crossed up from 28 → should still trigger."""
    candles = _make_candles(30, base_price=100.0, dip_last=0.03, bounce_last=True)
    indicators = _make_indicators(
        close=97.1, ema_20=100.0, bb_lower=97.0, bb_mid=100.0,
        bb_upper=103.0, rsi=32.0, atr=1.5,  # Above 30 but crossed up
    )
    prev_indicators = {"rsi_14": 28.0}  # Was below 30
    candles[-2]["close"] = 96.5
    candles[-1]["close"] = 97.1

    sig = detect_mean_reversion(candles, indicators, prev_indicators, regime="RANGE")

    assert sig.valid, f"Expected trigger on RSI cross-up, got: {sig.reason}"
    assert "crossed up" in sig.reason.lower()


if __name__ == "__main__":
    tests = [
        test_oversold_bounce_triggers,
        test_trend_regime_blocks,
        test_rsi_not_oversold_blocks,
        test_no_bounce_blocks,
        test_strategy_evaluate_returns_signal,
        test_candidate_scorer,
        test_candidate_scorer_low_in_trend,
        test_crash_regime_blocks,
        test_rsi_cross_up_triggers,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
