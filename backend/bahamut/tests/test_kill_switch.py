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


class MockExecutionEngine:
    """Minimal mock for ExecutionEngine."""
    def __init__(self):
        self.open_positions = []
        self.closed_trades = []

    def get_strategy_pnl(self, strategy):
        return sum(t.pnl for t in self.closed_trades if t.strategy == strategy)

    def get_strategy_unrealized(self, strategy):
        return sum(p.unrealized_pnl for p in self.open_positions if p.strategy == strategy)


@dataclass
class MockPosition:
    strategy: str = "v5_base"
    asset: str = "BTCUSD"
    direction: str = "LONG"
    unrealized_pnl: float = 0.0
    risk_amount: float = 0.0
    entry_price: float = 68000.0
    current_price: float = 68000.0
    stop_price: float = 65000.0
    tp_price: float = 72000.0
    size: float = 0.01
    order_id: str = "test-001"
    bars_held: int = 0


@dataclass
class MockClosedTrade:
    strategy: str = "v5_base"
    asset: str = "BTCUSD"
    direction: str = "LONG"
    pnl: float = 0.0
    exit_reason: str = "TP"
    entry_price: float = 68000.0
    exit_price: float = 70000.0
    order_id: str = "test-002"
    trade_id: str = "t-002"
    bars_held: int = 5


def _make_manager(threshold=0.10):
    """Create a PortfolioManager with mocked execution engine."""
    from bahamut.portfolio.manager import PortfolioManager
    pm = PortfolioManager(total_capital=100_000.0, max_drawdown_pct=threshold)
    return pm


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_zero_drawdown_no_trigger(mock_get_engine):
    """0% drawdown → kill switch must NOT trigger."""
    engine = MockExecutionEngine()
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.05)
    pm.update()

    assert pm.kill_switch_triggered is False, \
        f"Kill switch fired at 0% drawdown! equity={pm.total_capital}, peak={pm.peak_equity}"
    assert pm.total_drawdown == 0.0


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_3pct_drawdown_5pct_threshold_no_trigger(mock_get_engine):
    """-3% drawdown with 5% threshold → NO trigger."""
    engine = MockExecutionEngine()
    # Simulate -3% loss on v5_base sleeve (35% allocation = $35K)
    engine.closed_trades.append(MockClosedTrade(strategy="v5_base", pnl=-3000.0))
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.05)
    pm.update()

    dd = pm.total_drawdown
    assert pm.kill_switch_triggered is False, \
        f"Kill switch fired at {dd*100:.1f}% drawdown with 5% threshold!"
    assert dd < 0.05


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_6pct_drawdown_5pct_threshold_triggers(mock_get_engine):
    """-6% drawdown with 5% threshold → SHOULD trigger."""
    engine = MockExecutionEngine()
    # Simulate -6% loss spread across sleeves
    engine.closed_trades.append(MockClosedTrade(strategy="v5_base", pnl=-3000.0))
    engine.closed_trades.append(MockClosedTrade(strategy="v5_tuned", pnl=-3000.0))
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.05)
    pm.update()

    dd = pm.total_drawdown
    assert pm.kill_switch_triggered is True, \
        f"Kill switch did NOT fire at {dd*100:.1f}% drawdown with 5% threshold!"
    assert dd >= 0.05


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_threshold_zero_never_triggers(mock_get_engine):
    """If threshold == 0, kill switch must NEVER trigger (guard)."""
    engine = MockExecutionEngine()
    engine.closed_trades.append(MockClosedTrade(strategy="v5_base", pnl=-10000.0))
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.0)
    pm.update()

    assert pm.kill_switch_triggered is False, \
        "Kill switch fired with threshold=0! This is the zero-threshold guard bug."


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_test_trade_excluded_from_drawdown(mock_get_engine):
    """Test trades (strategy starting with TEST_) must NOT affect drawdown.
    Sleeve accounting naturally excludes them since no sleeve is named TEST_*."""
    engine = MockExecutionEngine()
    # Big test trade loss — but strategy doesn't match any sleeve
    engine.closed_trades.append(MockClosedTrade(strategy="TEST_test_trade", pnl=-20000.0))
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.05)
    pm.update()

    assert pm.kill_switch_triggered is False, \
        "Kill switch fired from test trade PnL! Test trades must be excluded."
    # Drawdown should be 0: test trade strategy doesn't match any sleeve,
    # so sleeve equity is unaffected
    assert pm.total_drawdown == 0.0, \
        f"Drawdown = {pm.total_drawdown*100:.1f}% but should be 0% (test trade excluded)"


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_test_position_excluded_from_risk(mock_get_engine):
    """Open test positions must NOT affect total risk in can_trade() check."""
    engine = MockExecutionEngine()
    # Open test position with high risk amount
    engine.open_positions.append(MockPosition(
        strategy="TEST_test_trade", risk_amount=50000.0))
    mock_get_engine.return_value = engine

    pm = _make_manager(threshold=0.05)
    can, reason = pm.can_trade("v5_base", "BTCUSD")
    assert can is True, f"can_trade blocked by test position risk! reason={reason}"


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


@patch("bahamut.portfolio.manager.get_execution_engine")
def test_kill_switch_log_contains_required_fields(mock_get_engine):
    """When kill switch triggers, log must contain equity, peak, drawdown, threshold, reason."""
    engine = MockExecutionEngine()
    engine.closed_trades.append(MockClosedTrade(strategy="v5_base", pnl=-6000.0))
    engine.closed_trades.append(MockClosedTrade(strategy="v5_tuned", pnl=-6000.0))
    mock_get_engine.return_value = engine

    with patch("bahamut.portfolio.manager.logger") as mock_logger:
        pm = _make_manager(threshold=0.05)
        pm.update()

        assert pm.kill_switch_triggered is True
        # Verify the warning log was called with required fields
        mock_logger.warning.assert_called()
        call_kwargs = mock_logger.warning.call_args
        # structlog passes as kwargs
        if call_kwargs.kwargs:
            kw = call_kwargs.kwargs
        else:
            # positional args: event name, then kwargs
            kw = call_kwargs[1] if len(call_kwargs) > 1 else {}

        required_fields = {"equity", "peak_equity", "drawdown", "threshold", "reason"}
        present_fields = set(kw.keys())
        missing = required_fields - present_fields
        assert not missing, f"Kill switch log missing fields: {missing}. Got: {present_fields}"


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
