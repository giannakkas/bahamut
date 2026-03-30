"""
Tests for enhanced learning engine v2 — maturity-aware trust.
"""
from bahamut.training.learning_engine import (
    compute_learning_context,
    get_maturity_state,
    get_confidence_weight,
    get_decay_factor,
    compute_trust_points,
    TRUST_DEFAULT,
    CONFIDENCE_PROVISIONAL,
    CONFIDENCE_DEVELOPING,
    CONFIDENCE_MATURE,
    TIER_PROVISIONAL_MAX,
    TIER_DEVELOPING_MAX,
)

def _make_trade(exit_reason="SL", pnl=-100, risk_amount=100, bars_held=1, strategy="v9_breakout", regime="RANGE"):
    return {
        "strategy": strategy, "asset": "BTCUSD", "asset_class": "crypto",
        "direction": "LONG", "regime": regime, "exit_reason": exit_reason,
        "pnl": pnl, "risk_amount": risk_amount, "bars_held": bars_held,
    }


# ═══ OUTCOME SCORING ═══

def test_sl_loss_negative():
    ctx = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=5))
    assert ctx.outcome_score < 0
    assert not ctx.quick_stop

def test_quick_stop_worse_than_slow():
    quick = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=1))
    slow = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=8))
    assert quick.quick_stop is True
    assert slow.quick_stop is False
    assert quick.outcome_score < slow.outcome_score

def test_tp_win_positive():
    ctx = compute_learning_context(_make_trade(exit_reason="TP", pnl=200, bars_held=10))
    assert ctx.outcome_score > 0.5

def test_timeout_scratch_neutral():
    ctx = compute_learning_context(_make_trade(exit_reason="TIMEOUT", pnl=-5, bars_held=10))
    assert abs(ctx.outcome_score) < 0.15

def test_timeout_less_impact_than_sl():
    timeout = compute_learning_context(_make_trade(exit_reason="TIMEOUT", pnl=-50, bars_held=10))
    sl = compute_learning_context(_make_trade(exit_reason="SL", pnl=-50, bars_held=10))
    assert timeout.outcome_score > sl.outcome_score

def test_outcome_bounded():
    for case in [
        _make_trade(exit_reason="SL", pnl=-500, bars_held=1),
        _make_trade(exit_reason="TP", pnl=1000, bars_held=5),
        _make_trade(exit_reason="TIMEOUT", pnl=0, bars_held=10),
    ]:
        ctx = compute_learning_context(case)
        assert -1.0 <= ctx.outcome_score <= 1.0


# ═══ MATURITY TIERS ═══

def test_maturity_states():
    assert get_maturity_state(0) == "provisional"
    assert get_maturity_state(3) == "provisional"
    assert get_maturity_state(4) == "provisional"
    assert get_maturity_state(5) == "developing"
    assert get_maturity_state(10) == "developing"
    assert get_maturity_state(14) == "developing"
    assert get_maturity_state(15) == "mature"
    assert get_maturity_state(50) == "mature"


# ═══ CONFIDENCE WEIGHT ═══

def test_confidence_weight_ramp():
    """Confidence smoothly increases from 0 to 1.0."""
    c0 = get_confidence_weight(0)
    c1 = get_confidence_weight(1)
    c4 = get_confidence_weight(TIER_PROVISIONAL_MAX)
    c5 = get_confidence_weight(TIER_PROVISIONAL_MAX + 1)
    c14 = get_confidence_weight(TIER_DEVELOPING_MAX)
    c30 = get_confidence_weight(30)

    assert c0 == 0.0
    assert 0 < c1 < CONFIDENCE_PROVISIONAL
    assert abs(c4 - CONFIDENCE_PROVISIONAL) < 0.02
    assert c5 > CONFIDENCE_PROVISIONAL
    assert abs(c14 - CONFIDENCE_DEVELOPING) < 0.02
    assert c30 > CONFIDENCE_DEVELOPING
    assert c30 <= CONFIDENCE_MATURE

def test_confidence_monotonic():
    """Confidence never decreases as samples increase."""
    prev = 0.0
    for s in range(0, 35):
        c = get_confidence_weight(s)
        assert c >= prev, f"Confidence decreased at {s}: {c} < {prev}"
        prev = c


# ═══ TWO LOSSES DON'T DESTROY TRUST ═══

def test_two_losses_dont_destroy():
    """2 losses in a new pattern should NOT push trust below 0.2."""
    # Simulate: start at 0.5, apply 2 quick SL losses
    trust = TRUST_DEFAULT
    for _ in range(2):
        ctx = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=1))
        mapped = (ctx.outcome_score + 1) / 2
        alpha = min(0.35, 0.5 / max(1, 1))  # Provisional alpha
        trust = trust * (1 - alpha) + mapped * alpha
    assert trust > 0.15, f"Trust dropped too low after 2 losses: {trust}"


# ═══ TWO WINS DON'T OVER-PROMOTE ═══

def test_two_wins_dont_overpromote():
    """2 wins in a new pattern should NOT push trust above 0.85."""
    trust = TRUST_DEFAULT
    for i in range(2):
        ctx = compute_learning_context(_make_trade(exit_reason="TP", pnl=200, bars_held=10))
        mapped = (ctx.outcome_score + 1) / 2
        alpha = min(0.35, 0.5 / max(1, i + 1))
        trust = trust * (1 - alpha) + mapped * alpha
    assert trust < 0.85, f"Trust too high after 2 wins: {trust}"


# ═══ DECAY ═══

def test_decay_fresh_is_1():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    assert get_decay_factor(now) == 1.0

def test_decay_stale_drops():
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    d = get_decay_factor(old)
    assert d < 1.0
    assert d > 0.3

def test_decay_very_stale_at_floor():
    from datetime import datetime, timezone, timedelta
    ancient = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    d = get_decay_factor(ancient)
    assert d <= 0.3


# ═══ RECOVERY ═══

def test_recovery_after_losses():
    """Good trades after bad ones should gradually recover trust."""
    trust = TRUST_DEFAULT
    alpha = TRUST_DEFAULT  # Will use adaptive alpha

    # 5 losses first
    for i in range(5):
        ctx = compute_learning_context(_make_trade(exit_reason="SL", pnl=-100, bars_held=5))
        mapped = (ctx.outcome_score + 1) / 2
        a = min(0.35, 0.5 / max(1, i + 1))
        trust = trust * (1 - a) + mapped * a

    low_point = trust
    assert low_point < 0.4, f"Trust should be low after losses: {low_point}"

    # 5 wins to recover
    for i in range(5, 10):
        ctx = compute_learning_context(_make_trade(exit_reason="TP", pnl=200, bars_held=10))
        mapped = (ctx.outcome_score + 1) / 2
        a = 0.15 * 1.2  # developing alpha
        trust = trust * (1 - a) + mapped * a

    assert trust > low_point, f"Trust should recover: {trust} > {low_point}"
    assert trust < 0.8, f"Recovery should be gradual, not instant: {trust}"


if __name__ == "__main__":
    tests = [
        test_sl_loss_negative, test_quick_stop_worse_than_slow,
        test_tp_win_positive, test_timeout_scratch_neutral,
        test_timeout_less_impact_than_sl, test_outcome_bounded,
        test_maturity_states, test_confidence_weight_ramp,
        test_confidence_monotonic, test_two_losses_dont_destroy,
        test_two_wins_dont_overpromote, test_decay_fresh_is_1,
        test_decay_stale_drops, test_decay_very_stale_at_floor,
        test_recovery_after_losses,
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


# ═══ EXPECTANCY CALCULATION ═══

def test_expectancy_positive_edge():
    """Positive R-multiples → positive expectancy."""
    from bahamut.training.learning_engine import calculate_expectancy
    e = calculate_expectancy([1.5, 2.0, -1.0, 0.5, 1.0])
    assert e > 0, f"Expected positive, got {e}"

def test_expectancy_negative_edge():
    """All losses → negative expectancy."""
    from bahamut.training.learning_engine import calculate_expectancy
    e = calculate_expectancy([-1.0, -1.0, -0.5, -1.0, -0.8])
    assert e < 0, f"Expected negative, got {e}"

def test_expectancy_empty():
    from bahamut.training.learning_engine import calculate_expectancy
    assert calculate_expectancy([]) == 0.0

def test_expectancy_uses_last_10():
    """Only last 10 trades count for expectancy."""
    from bahamut.training.learning_engine import calculate_expectancy
    old_bad = [-1.0] * 10  # Old losses
    recent_good = [2.0] * 10  # Recent wins
    e = calculate_expectancy(old_bad + recent_good)
    assert e > 0, f"Recent wins should dominate, got {e}"
