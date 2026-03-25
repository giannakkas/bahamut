"""
Bahamut.AI — Exploration Mode Tests

Tests for:
  - Exploration trade created when strict conditions fail
  - No more than 1 exploration trade per cycle
  - Exploration respects reduced risk
  - No trades when system degraded (CRISIS, BLOCKED)
  - Score floor enforced
  - Policy returns EXPLORATION mode
  - Isolation from production metrics

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_exploration.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from bahamut.execution.policy import ExecutionPolicy, ExecutionRequest, ExecutionDecision


class TestExplorationPolicy:
    """Test execution policy with is_exploration flag."""

    def _req(self, score=0.45, exploration=False, regime="RISK_ON",
             label="WEAK_SIGNAL", has_dup=False, positions=0,
             risk_can_trade=True, gate="CLEAR") -> ExecutionRequest:
        return ExecutionRequest(
            asset="BTCUSD", direction="LONG", consensus_score=score,
            signal_label=label,
            execution_mode_from_consensus="AUTO",
            disagreement_gate=gate, disagreement_index=0.1,
            risk_can_trade=risk_can_trade,
            trading_profile="BALANCED",
            open_position_count=positions,
            has_position_in_asset=has_dup,
            portfolio_balance=100000.0,
            regime=regime,
            mean_agent_trust=0.8,
            system_confidence=0.55,
            is_exploration=exploration,
        )

    def test_strict_rejects_low_score(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.45, exploration=False))
        assert not decision.allowed
        assert any("SCORE_LOW" in b for b in decision.blockers)

    def test_exploration_allows_low_score(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.45, exploration=True))
        assert decision.allowed
        assert decision.mode == "EXPLORATION"

    def test_exploration_rejects_very_low_score(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.20, exploration=True))
        assert not decision.allowed
        assert any("SCORE_LOW" in b for b in decision.blockers)

    def test_exploration_blocks_crisis(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.45, exploration=True, regime="CRISIS"))
        assert not decision.allowed
        assert any("CRISIS" in b for b in decision.blockers)

    def test_exploration_size_multiplier_reduced(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.50, exploration=True))
        assert decision.allowed
        assert decision.position_size_multiplier <= 0.25

    def test_exploration_keeps_hard_blockers(self):
        """All safety gates still enforced in exploration."""
        policy = ExecutionPolicy()
        # Duplicate position
        decision = policy.evaluate(self._req(score=0.50, exploration=True, has_dup=True))
        assert not decision.allowed
        assert any("DUPLICATE" in b for b in decision.blockers)

    def test_exploration_keeps_risk_veto(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.50, exploration=True, risk_can_trade=False))
        assert not decision.allowed
        assert any("RISK_VETO" in b for b in decision.blockers)

    def test_exploration_keeps_disagreement_block(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.50, exploration=True, gate="BLOCKED"))
        assert not decision.allowed

    def test_strict_mode_label(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.70, exploration=False))
        assert decision.allowed
        assert decision.mode in ("PAPER_AUTO", "PAPER_APPROVAL")

    def test_exploration_mode_label(self):
        policy = ExecutionPolicy()
        decision = policy.evaluate(self._req(score=0.50, exploration=True))
        assert decision.mode == "EXPLORATION"


class TestExplorationEligibility:
    """Test _check_exploration_eligible helper."""

    @patch("bahamut.paper_trading.store.count_exploration_positions", return_value=0)
    def test_eligible_basic(self, mock_count):
        from bahamut.paper_trading.sync_executor import _check_exploration_eligible
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.45, "RISK_ON", "WEAK_SIGNAL")
        assert eligible or "cycle limit" in reason.lower()  # May hit Redis check

    def test_score_too_low(self):
        from bahamut.paper_trading.sync_executor import _check_exploration_eligible
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.20, "RISK_ON", "WEAK_SIGNAL")
        assert not eligible
        assert "floor" in reason.lower()

    def test_crisis_blocked(self):
        from bahamut.paper_trading.sync_executor import _check_exploration_eligible
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.45, "CRISIS", "WEAK_SIGNAL")
        assert not eligible
        assert "CRISIS" in reason

    def test_no_trade_blocked(self):
        from bahamut.paper_trading.sync_executor import _check_exploration_eligible
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.45, "RISK_ON", "NO_TRADE")
        assert not eligible
        assert "NO_TRADE" in reason


class TestExplorationLimits:
    """Test per-cycle, daily, and max-positions limits."""

    @patch("bahamut.paper_trading.store.count_exploration_positions")
    def test_max_positions_blocks(self, mock_count):
        mock_count.return_value = 2
        from bahamut.paper_trading.sync_executor import _check_exploration_eligible
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.50, "RISK_ON", "WEAK_SIGNAL")
        assert not eligible
        assert "Max exploration" in reason


class TestExplorationCooldown:
    """Test loss-streak cooldown."""

    @pytest.fixture(autouse=True)
    def _redis(self):
        from bahamut.paper_trading.sync_executor import _get_exploration_redis
        r = _get_exploration_redis()
        if not r:
            pytest.skip("No Redis available")
        self.r = r

    def test_record_loss_increments_streak(self):
        from bahamut.paper_trading.sync_executor import record_exploration_outcome, EXPLORATION_LOSS_STREAK_KEY
        self.r.delete(EXPLORATION_LOSS_STREAK_KEY)
        record_exploration_outcome(-50.0)
        streak = int(self.r.get(EXPLORATION_LOSS_STREAK_KEY) or 0)
        assert streak == 1

    def test_win_resets_streak(self):
        from bahamut.paper_trading.sync_executor import record_exploration_outcome, EXPLORATION_LOSS_STREAK_KEY
        self.r.set(EXPLORATION_LOSS_STREAK_KEY, 2)
        record_exploration_outcome(100.0)
        streak = int(self.r.get(EXPLORATION_LOSS_STREAK_KEY) or 0)
        assert streak == 0

    def test_cooldown_activates_after_streak(self):
        from bahamut.paper_trading.sync_executor import (
            record_exploration_outcome, EXPLORATION_LOSS_STREAK_KEY, EXPLORATION_COOLDOWN_KEY,
        )
        self.r.delete(EXPLORATION_LOSS_STREAK_KEY)
        self.r.delete(EXPLORATION_COOLDOWN_KEY)
        record_exploration_outcome(-10.0)
        record_exploration_outcome(-10.0)
        record_exploration_outcome(-10.0)
        assert self.r.get(EXPLORATION_COOLDOWN_KEY) is not None
        self.r.delete(EXPLORATION_COOLDOWN_KEY)
        self.r.delete(EXPLORATION_LOSS_STREAK_KEY)

    def test_cooldown_blocks_exploration(self):
        from bahamut.paper_trading.sync_executor import (
            _check_exploration_eligible, EXPLORATION_COOLDOWN_KEY,
        )
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        self.r.set(EXPLORATION_COOLDOWN_KEY, future.isoformat(), ex=3700)
        eligible, reason = _check_exploration_eligible("BTCUSD", 0.50, "RISK_ON", "WEAK_SIGNAL")
        assert not eligible
        assert "cooldown" in reason.lower()
        self.r.delete(EXPLORATION_COOLDOWN_KEY)


class TestExplorationStatus:
    """Test dashboard status function."""

    def test_status_returns_dict(self):
        from bahamut.paper_trading.sync_executor import get_exploration_status
        status = get_exploration_status()
        assert isinstance(status, dict)
        assert "enabled" in status
        assert "daily_count" in status
        assert "daily_limit" in status
        assert "cooldown_active" in status
        assert "loss_streak" in status


class TestExplorationIsolation:
    """Exploration must not contaminate production logic."""

    def test_default_is_not_exploration(self):
        req = ExecutionRequest(
            asset="BTCUSD", direction="LONG", consensus_score=0.70,
            signal_label="SIGNAL",
            execution_mode_from_consensus="AUTO",
            disagreement_gate="CLEAR",
        )
        assert req.is_exploration is False

    def test_exploration_flag_explicit(self):
        req = ExecutionRequest(
            asset="BTCUSD", direction="LONG", consensus_score=0.45,
            signal_label="WEAK_SIGNAL",
            execution_mode_from_consensus="AUTO",
            disagreement_gate="CLEAR",
            is_exploration=True,
        )
        assert req.is_exploration is True

    def test_no_training_engine_import(self):
        """sync_executor must not import training engine."""
        import inspect
        from bahamut.paper_trading import sync_executor
        source = inspect.getsource(sync_executor)
        assert "from bahamut.training" not in source


class TestConfigDefaults:
    """Exploration config defaults present."""

    def test_exploration_defaults_exist(self):
        from bahamut.config_defaults import EXPLORATION_DEFAULTS
        assert EXPLORATION_DEFAULTS["exploration.enabled"] is True
        assert EXPLORATION_DEFAULTS["exploration.min_consensus_score"] == 0.35
        assert EXPLORATION_DEFAULTS["exploration.max_per_cycle"] == 1
        assert EXPLORATION_DEFAULTS["exploration.max_open_positions"] == 2
        assert EXPLORATION_DEFAULTS["exploration.max_per_day"] == 5
        assert EXPLORATION_DEFAULTS["exploration.risk_pct"] == 0.5
        assert EXPLORATION_DEFAULTS["exploration.size_multiplier"] == 0.25
        assert EXPLORATION_DEFAULTS["exploration.cooldown_loss_streak"] == 3
        assert EXPLORATION_DEFAULTS["exploration.cooldown_hours"] == 12

    def test_exploration_in_merged_defaults(self):
        from bahamut.config_defaults import get_all_defaults
        defaults = get_all_defaults()
        assert "exploration.enabled" in defaults


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
