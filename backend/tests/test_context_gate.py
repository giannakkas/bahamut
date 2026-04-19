"""
Tests for context gate and pattern suppression.
"""
from bahamut.trading.context_gate import (
    validate_strategy_context,
    pre_score_gate,
    get_pattern_key,
    STRATEGY_REGIME_MAP,
)


def test_v10_blocked_in_trend():
    r = validate_strategy_context("v10_mean_reversion", "TREND")
    assert not r["valid"]
    assert "invalid_regime" in r["gate"]

def test_v10_blocked_in_crash():
    r = validate_strategy_context("v10_mean_reversion", "CRASH")
    assert not r["valid"]
    assert "crash" in r["gate"]

def test_v10_allowed_in_range():
    r = validate_strategy_context("v10_mean_reversion", "RANGE")
    assert r["valid"]

def test_v9_allowed_in_trend():
    r = validate_strategy_context("v9_breakout", "TREND")
    assert r["valid"]
    assert r["penalty"] == 0

def test_v9_penalized_in_range():
    r = validate_strategy_context("v9_breakout", "RANGE")
    assert r["valid"]
    assert r["penalty"] > 0

def test_v9_blocked_in_crash():
    r = validate_strategy_context("v9_breakout", "CRASH")
    assert not r["valid"]

def test_v5_blocked_in_range():
    r = validate_strategy_context("v5_base", "RANGE")
    assert not r["valid"]

def test_v5_allowed_in_trend():
    r = validate_strategy_context("v5_base", "TREND")
    assert r["valid"]

def test_crash_blocks_everything():
    for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
        r = validate_strategy_context(strat, "CRASH")
        assert not r["valid"], f"{strat} should be blocked in CRASH"

def test_production_stricter():
    """v9 in RANGE allowed in training but blocked in production."""
    train = validate_strategy_context("v9_breakout", "RANGE", mode="TRAINING")
    prod = validate_strategy_context("v9_breakout", "RANGE", mode="PRODUCTION")
    assert train["valid"]
    assert not prod["valid"]

def test_pre_score_gate_blocks_v10_trend():
    r = pre_score_gate("v10_mean_reversion", "TREND", "crypto")
    assert not r["allowed"]

def test_pre_score_gate_allows_v10_range():
    r = pre_score_gate("v10_mean_reversion", "RANGE", "crypto")
    assert r["allowed"]

def test_pattern_key():
    k = get_pattern_key("v9_breakout", "RANGE", "crypto")
    assert k == "v9_breakout:RANGE:crypto"


if __name__ == "__main__":
    tests = [
        test_v10_blocked_in_trend, test_v10_blocked_in_crash,
        test_v10_allowed_in_range, test_v9_allowed_in_trend,
        test_v9_penalized_in_range, test_v9_blocked_in_crash,
        test_v5_blocked_in_range, test_v5_allowed_in_trend,
        test_crash_blocks_everything, test_production_stricter,
        test_pre_score_gate_blocks_v10_trend,
        test_pre_score_gate_allows_v10_range, test_pattern_key,
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
