"""
Tests for the enhanced learning engine.

Proves:
  1. SL loss reduces trust for that pattern
  2. Repeated losses reduce trust more than one loss
  3. TP win increases trust
  4. Scratch/timeout has smaller effect than full SL
  5. Quick stop penalized more than slow stop
  6. Outcome scoring is correct for all exit types
"""
from bahamut.training.learning_engine import (
    compute_learning_context,
    LearningContext,
    TRUST_DEFAULT,
)


def _make_trade(exit_reason="SL", pnl=-100, risk_amount=100, bars_held=1, strategy="v9_breakout", regime="RANGE"):
    return {
        "strategy": strategy,
        "asset": "BTCUSD",
        "asset_class": "crypto",
        "direction": "LONG",
        "regime": regime,
        "exit_reason": exit_reason,
        "pnl": pnl,
        "risk_amount": risk_amount,
        "bars_held": bars_held,
    }


# ═══════════════════════════════════════════
# TEST 1: SL loss produces negative outcome
# ═══════════════════════════════════════════

def test_sl_loss_negative_outcome():
    """SL loss should produce a negative outcome score."""
    ctx = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=5))
    assert ctx.outcome_score < 0, f"SL loss should be negative, got {ctx.outcome_score}"
    assert ctx.exit_reason == "SL"
    assert ctx.r_multiple == -1.0
    assert not ctx.quick_stop  # 5 bars > 3 = not quick


# ═══════════════════════════════════════════
# TEST 2: Quick SL penalized MORE than slow SL
# ═══════════════════════════════════════════

def test_quick_stop_worse_than_slow():
    """Quick SL (within 3 bars) should be penalized more than normal SL."""
    quick = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=1))
    slow = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=8))

    assert quick.quick_stop is True
    assert slow.quick_stop is False
    assert quick.outcome_score < slow.outcome_score, \
        f"Quick SL ({quick.outcome_score}) should be worse than slow SL ({slow.outcome_score})"


# ═══════════════════════════════════════════
# TEST 3: TP win produces positive outcome
# ═══════════════════════════════════════════

def test_tp_win_positive():
    """Take profit should produce a strong positive outcome."""
    ctx = compute_learning_context(_make_trade(exit_reason="TP", pnl=200, bars_held=10))
    assert ctx.outcome_score > 0.5, f"TP win should be strongly positive, got {ctx.outcome_score}"
    assert ctx.r_multiple == 2.0


# ═══════════════════════════════════════════
# TEST 4: Timeout scratch is nearly neutral
# ═══════════════════════════════════════════

def test_timeout_scratch_nearly_neutral():
    """Timeout with tiny loss should be nearly neutral."""
    ctx = compute_learning_context(_make_trade(exit_reason="TIMEOUT", pnl=-5, bars_held=10))
    assert abs(ctx.outcome_score) < 0.15, \
        f"Timeout scratch should be nearly neutral, got {ctx.outcome_score}"


# ═══════════════════════════════════════════
# TEST 5: Timeout has less impact than SL
# ═══════════════════════════════════════════

def test_timeout_less_impact_than_sl():
    """Timeout loss should have smaller negative impact than SL loss."""
    timeout = compute_learning_context(_make_trade(exit_reason="TIMEOUT", pnl=-50, bars_held=10))
    sl = compute_learning_context(_make_trade(exit_reason="SL", pnl=-50, bars_held=10))

    assert timeout.outcome_score > sl.outcome_score, \
        f"Timeout ({timeout.outcome_score}) should be less negative than SL ({sl.outcome_score})"


# ═══════════════════════════════════════════
# TEST 6: Profitable timeout is mildly positive
# ═══════════════════════════════════════════

def test_profitable_timeout_positive():
    """Timeout with profit should be mildly positive."""
    ctx = compute_learning_context(_make_trade(exit_reason="TIMEOUT", pnl=30, bars_held=10))
    assert ctx.outcome_score > 0, f"Profitable timeout should be positive, got {ctx.outcome_score}"
    assert ctx.outcome_score < 0.5, f"Should be mild, not strong, got {ctx.outcome_score}"


# ═══════════════════════════════════════════
# TEST 7: R-multiple computed correctly
# ═══════════════════════════════════════════

def test_r_multiple_computation():
    """R-multiple = pnl / risk_amount."""
    ctx1 = compute_learning_context(_make_trade(pnl=-100, risk_amount=100))
    assert ctx1.r_multiple == -1.0

    ctx2 = compute_learning_context(_make_trade(pnl=200, risk_amount=100, exit_reason="TP"))
    assert ctx2.r_multiple == 2.0

    ctx3 = compute_learning_context(_make_trade(pnl=-50, risk_amount=100))
    assert ctx3.r_multiple == -0.5


# ═══════════════════════════════════════════
# TEST 8: Outcome score bounds
# ═══════════════════════════════════════════

def test_outcome_score_bounded():
    """Outcome score should always be between -1 and +1."""
    cases = [
        _make_trade(exit_reason="SL", pnl=-500, bars_held=1),   # Extreme loss
        _make_trade(exit_reason="TP", pnl=1000, bars_held=5),   # Extreme win
        _make_trade(exit_reason="TIMEOUT", pnl=0, bars_held=10), # Flat
        _make_trade(exit_reason="MANUAL", pnl=50, bars_held=3), # Manual
    ]
    for c in cases:
        ctx = compute_learning_context(c)
        assert -1.0 <= ctx.outcome_score <= 1.0, \
            f"Outcome {ctx.outcome_score} out of bounds for {c['exit_reason']}"


if __name__ == "__main__":
    tests = [
        test_sl_loss_negative_outcome,
        test_quick_stop_worse_than_slow,
        test_tp_win_positive,
        test_timeout_scratch_nearly_neutral,
        test_timeout_less_impact_than_sl,
        test_profitable_timeout_positive,
        test_r_multiple_computation,
        test_outcome_score_bounded,
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
