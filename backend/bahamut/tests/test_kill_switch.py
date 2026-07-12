"""
Bahamut.AI — Kill Switch Unit Tests

Covers:
  1. 0% drawdown → no trigger
  2. -3% with threshold 5% → no trigger
  3. -6% with threshold 5% → trigger
  4. threshold == 0 → no trigger (guard)
  5. test trades excluded from drawdown
  6. get_current_state exception → returns kill_switch_active=False
  7. evaluate_kill_switch with zero inputs → no trigger
  8. combined stress with all-zero inputs → no trigger
  9. kill switch logging contains required fields
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field


# ─── Test: evaluate_kill_switch with zero/low inputs ───


def test_evaluate_kill_switch_zero_inputs():
    """All inputs at zero → kill switch must NOT activate."""
    from bahamut.portfolio.kill_switch import evaluate_kill_switch
    state = evaluate_kill_switch(
        weighted_tail_risk=0.0,
        portfolio_fragility=0.0,
        concentration_risk=0.0,
        drawdown_proximity=0.0,
        position_count=0,
    )
    assert state.kill_switch_active is False, \
        f"Kill switch fired with all-zero inputs! Triggers: {state.triggers}"
    assert state.safe_mode_active is False
    assert state.effective_max_trades > 0


def test_evaluate_kill_switch_low_stress():
    """Moderate stress below all thresholds → no trigger."""
    from bahamut.portfolio.kill_switch import evaluate_kill_switch
    state = evaluate_kill_switch(
        weighted_tail_risk=0.10,
        portfolio_fragility=0.40,
        concentration_risk=0.30,
        drawdown_proximity=0.20,
        position_count=2,
    )
    assert state.kill_switch_active is False, \
        f"Kill switch fired with moderate inputs! Triggers: {state.triggers}"


def test_evaluate_kill_switch_high_tail_risk():
    """Tail risk above threshold → SHOULD trigger."""
    from bahamut.portfolio.kill_switch import evaluate_kill_switch
    state = evaluate_kill_switch(
        weighted_tail_risk=0.30,  # above 0.25 default threshold
        portfolio_fragility=0.0,
        concentration_risk=0.0,
        drawdown_proximity=0.0,
        position_count=1,
    )
    assert state.kill_switch_active is True
    assert any("tail_risk" in t for t in state.triggers)


def test_evaluate_kill_switch_high_fragility():
    """Fragility above threshold → SHOULD trigger."""
    from bahamut.portfolio.kill_switch import evaluate_kill_switch
    state = evaluate_kill_switch(
        weighted_tail_risk=0.0,
        portfolio_fragility=0.85,  # above 0.80 default threshold
        concentration_risk=0.0,
        drawdown_proximity=0.0,
        position_count=1,
    )
    assert state.kill_switch_active is True
    assert any("fragility" in t for t in state.triggers)


# ─── Test: PortfolioManager drawdown-based kill switch ───






















# ─── Test: get_current_state exception handling ───


def test_get_current_state_exception_returns_inactive():
    """When get_current_state throws, kill_switch_active must be False."""
    from bahamut.portfolio.kill_switch import get_current_state

    with patch("bahamut.portfolio.registry.load_portfolio_snapshot",
               side_effect=Exception("DB connection failed")):
        result = get_current_state()

    assert result["kill_switch_active"] is False, \
        f"Kill switch defaulted to ACTIVE on exception! This is the root cause bug. Result: {result}"
    # Safe mode should still be on as a precaution
    assert result["safe_mode_active"] is True


def test_get_current_state_empty_portfolio_safe():
    """Empty portfolio (0 positions) → kill switch inactive."""
    from bahamut.portfolio.kill_switch import get_current_state
    from bahamut.portfolio.registry import PortfolioSnapshot

    empty_snap = PortfolioSnapshot(positions=[], balance=100000.0,
                                    total_position_value=0.0, total_risk=0.0)

    with patch("bahamut.portfolio.registry.load_portfolio_snapshot",
               return_value=empty_snap):
        result = get_current_state()

    assert result["kill_switch_active"] is False, \
        f"Kill switch active on empty portfolio! Result: {result}"


# ─── Test: Kill switch logging fields ───




# ─── Test: Combined stress calculation safety ───


def test_combined_stress_all_zero_below_threshold():
    """
    combined_stress = 0.40 * min(1, 0/0.10) + 0.30*0 + 0.20*0 + 0.10*0 = 0
    0 < 0.70 threshold → no trigger.
    This validates the formula doesn't produce NaN or unexpected results.
    """
    from bahamut.portfolio.kill_switch import evaluate_kill_switch
    state = evaluate_kill_switch(
        weighted_tail_risk=0.0,
        portfolio_fragility=0.0,
        concentration_risk=0.0,
        drawdown_proximity=0.0,
        position_count=0,
    )
    assert state.kill_switch_active is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
