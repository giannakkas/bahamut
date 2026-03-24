"""
Bahamut.AI — Adaptive Thresholds Tests

Tests for:
  - No adaptation below min samples
  - Conservative mode when performance poor
  - Aggressive mode when performance strong
  - Balanced mode otherwise
  - Thresholds never exceed bounds
  - Incremental steps (no large jumps)
  - Cooldown prevents frequent changes
  - Early execution disabled in conservative
  - Emergency override on extreme drawdown
  - Audit log records changes

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_adaptive_thresholds.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from bahamut.training.adaptive_thresholds import (
    ThresholdProfile, RollingMetrics, BOUNDS, POLICY, MODE_PROFILES,
    choose_mode, compute_threshold_updates, run_adaptive_update,
    _step_toward, _step_toward_float,
)


def _metrics(
    win_rate=0.5, profit_factor=1.2, drawdown_pct=2.0,
    stop_out_rate=0.3, total_trades=50, expectancy=5.0,
    early_win_rate=0.5, standard_win_rate=0.5,
    early_count=5, standard_count=45,
    recent_win_rate=0.5, recent_profit_factor=1.2,
) -> RollingMetrics:
    return RollingMetrics(
        total_trades=total_trades, win_rate=win_rate,
        profit_factor=profit_factor, expectancy=expectancy,
        avg_pnl=expectancy, drawdown_pct=drawdown_pct,
        stop_out_rate=stop_out_rate, early_win_rate=early_win_rate,
        standard_win_rate=standard_win_rate,
        early_count=early_count, standard_count=standard_count,
        recent_win_rate=recent_win_rate,
        recent_profit_factor=recent_profit_factor,
    )


class TestModeSelection:
    def test_conservative_on_low_win_rate(self):
        m = _metrics(win_rate=0.30)
        assert choose_mode(m) == "CONSERVATIVE"

    def test_conservative_on_low_profit_factor(self):
        m = _metrics(profit_factor=0.7)
        assert choose_mode(m) == "CONSERVATIVE"

    def test_conservative_on_high_drawdown(self):
        m = _metrics(drawdown_pct=6.0)
        assert choose_mode(m) == "CONSERVATIVE"

    def test_conservative_on_high_stop_out(self):
        m = _metrics(stop_out_rate=0.55)
        assert choose_mode(m) == "CONSERVATIVE"

    def test_aggressive_when_all_strong(self):
        m = _metrics(win_rate=0.60, profit_factor=2.0, drawdown_pct=0.5, stop_out_rate=0.15)
        assert choose_mode(m) == "AGGRESSIVE"

    def test_not_aggressive_if_one_metric_weak(self):
        # High win rate but high drawdown — not aggressive
        m = _metrics(win_rate=0.60, profit_factor=2.0, drawdown_pct=3.0, stop_out_rate=0.15)
        assert choose_mode(m) != "AGGRESSIVE"

    def test_balanced_default(self):
        m = _metrics(win_rate=0.48, profit_factor=1.1, drawdown_pct=2.0, stop_out_rate=0.3)
        assert choose_mode(m) == "BALANCED"


class TestBoundsEnforcement:
    def test_step_toward_respects_bounds(self):
        # Try to go below minimum
        result = _step_toward(76, 70, 5, 75, 90)
        assert result >= 75
        # Try to go above maximum
        result = _step_toward(88, 95, 5, 75, 90)
        assert result <= 90

    def test_step_toward_float_respects_bounds(self):
        result = _step_toward_float(0.3, 0.1, 0.15, 0.25, 1.0)
        assert result >= 0.25
        result = _step_toward_float(0.9, 1.5, 0.15, 0.25, 1.0)
        assert result <= 1.0

    def test_max_step_limits_change(self):
        # Max step is 3 for standard_threshold
        result = _step_toward(80, 90, 3, 75, 90)
        assert result == 83  # Only moved by 3, not 10

    def test_compute_updates_within_bounds(self):
        current = ThresholdProfile.default()
        current.mode = "BALANCED"
        metrics = _metrics()
        for mode in ["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]:
            new = compute_threshold_updates(current, mode, metrics)
            assert BOUNDS["standard_threshold"]["min"] <= new.standard_threshold <= BOUNDS["standard_threshold"]["max"]
            assert BOUNDS["early_threshold"]["min"] <= new.early_threshold <= BOUNDS["early_threshold"]["max"]
            assert BOUNDS["max_early_per_cycle"]["min"] <= new.max_early_per_cycle <= BOUNDS["max_early_per_cycle"]["max"]
            assert BOUNDS["early_risk_multiplier"]["min"] <= new.early_risk_multiplier <= BOUNDS["early_risk_multiplier"]["max"]


class TestIncrementalAdjustment:
    def test_no_large_jumps(self):
        current = ThresholdProfile.default()
        current.mode = "BALANCED"
        current.standard_threshold = 80
        metrics = _metrics()
        new = compute_threshold_updates(current, "CONSERVATIVE", metrics)
        # Conservative target is 85, but max step is 3
        assert abs(new.standard_threshold - current.standard_threshold) <= 3

    def test_gradual_convergence(self):
        """Repeated calls should converge toward target."""
        current = ThresholdProfile.default()
        current.mode = "BALANCED"
        current.standard_threshold = 80
        metrics = _metrics()
        for _ in range(10):
            current = compute_threshold_updates(current, "CONSERVATIVE", metrics)
        # Should have reached or be very close to conservative target (85)
        assert current.standard_threshold >= 83


class TestWarmingUp:
    @patch("bahamut.training.adaptive_thresholds.compute_rolling_metrics")
    @patch("bahamut.training.adaptive_thresholds.persist_profile")
    @patch("bahamut.training.adaptive_thresholds.persist_metrics")
    @patch("bahamut.training.adaptive_thresholds.get_current_profile")
    def test_no_adaptation_below_min_samples(self, mock_profile, mock_pm, mock_pp, mock_metrics):
        mock_profile.return_value = ThresholdProfile.default()
        mock_metrics.return_value = _metrics(total_trades=10)
        result = run_adaptive_update()
        assert result.mode == "WARMING_UP"
        # Default already has WARMING_UP with default reason
        assert result.standard_threshold == BOUNDS["standard_threshold"]["default"]


class TestCooldown:
    @patch("bahamut.training.adaptive_thresholds.compute_rolling_metrics")
    @patch("bahamut.training.adaptive_thresholds.persist_profile")
    @patch("bahamut.training.adaptive_thresholds.persist_metrics")
    @patch("bahamut.training.adaptive_thresholds.get_current_profile")
    def test_cooldown_prevents_change(self, mock_profile, mock_pm, mock_pp, mock_metrics):
        profile = ThresholdProfile.default()
        profile.mode = "BALANCED"
        profile.trades_since_last_adjustment = 3  # Below cooldown of 10
        mock_profile.return_value = profile
        mock_metrics.return_value = _metrics(total_trades=50)
        result = run_adaptive_update()
        # Should increment counter but not change mode
        assert result.trades_since_last_adjustment == 4


class TestConservativeMode:
    def test_early_execution_disabled(self):
        current = ThresholdProfile.default()
        current.mode = "BALANCED"
        metrics = _metrics()
        new = compute_threshold_updates(current, "CONSERVATIVE", metrics)
        assert new.early_execution_enabled is False
        assert new.max_early_per_cycle == 0  # May take multiple steps

    def test_thresholds_tightened(self):
        current = ThresholdProfile.default()
        current.mode = "BALANCED"
        current.standard_threshold = 80
        metrics = _metrics()
        new = compute_threshold_updates(current, "CONSERVATIVE", metrics)
        assert new.standard_threshold > current.standard_threshold


class TestEmergency:
    @patch("bahamut.training.adaptive_thresholds.compute_rolling_metrics")
    @patch("bahamut.training.adaptive_thresholds.persist_profile")
    @patch("bahamut.training.adaptive_thresholds.persist_metrics")
    @patch("bahamut.training.adaptive_thresholds._append_audit")
    @patch("bahamut.training.adaptive_thresholds.get_current_profile")
    def test_emergency_on_extreme_drawdown(self, mock_profile, mock_audit, mock_pm, mock_pp, mock_metrics):
        profile = ThresholdProfile.default()
        profile.mode = "AGGRESSIVE"
        profile.trades_since_last_adjustment = 20  # Past cooldown
        mock_profile.return_value = profile
        mock_metrics.return_value = _metrics(total_trades=50, win_rate=0.20, drawdown_pct=12.0)
        result = run_adaptive_update()
        assert result.mode == "CONSERVATIVE"
        assert result.early_execution_enabled is False
        assert "EMERGENCY" in result.last_adjustment_reason


class TestAudit:
    @patch("bahamut.training.adaptive_thresholds._append_audit")
    @patch("bahamut.training.adaptive_thresholds.compute_rolling_metrics")
    @patch("bahamut.training.adaptive_thresholds.persist_profile")
    @patch("bahamut.training.adaptive_thresholds.persist_metrics")
    @patch("bahamut.training.adaptive_thresholds.get_current_profile")
    def test_audit_called_on_adjustment(self, mock_profile, mock_pm, mock_pp, mock_metrics, mock_audit):
        profile = ThresholdProfile.default()
        profile.mode = "BALANCED"
        profile.trades_since_last_adjustment = 20  # Past cooldown
        mock_profile.return_value = profile
        mock_metrics.return_value = _metrics(total_trades=50)
        run_adaptive_update()
        mock_audit.assert_called_once()


class TestIsolation:
    def test_no_production_imports(self):
        import inspect
        from bahamut.training import adaptive_thresholds
        source = inspect.getsource(adaptive_thresholds)
        assert "from bahamut.execution" not in source
        assert "import ExecutionEngine" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
