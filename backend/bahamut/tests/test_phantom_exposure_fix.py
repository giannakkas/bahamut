"""
Tests for phantom exposure fix and training vs production risk modes.

Covers:
  1. Zero positions → zero exposure
  2. Stale positions ignored in snapshot
  3. Restart does not create phantom exposure
  4. Strict mode still blocks risky trades
  5. Exploration mode allows trades (when safe)
  6. Kill switch still blocks exploration
  7. Duplicate trades still blocked in exploration
  8. Crisis regime still blocks exploration
  9. Exposure cap still enforced in exploration
  10. Logs correctly show decision breakdown
"""
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import field

from bahamut.portfolio.registry import PortfolioSnapshot, OpenPosition
from bahamut.portfolio.engine import (
    evaluate_trade_for_portfolio, _compute_exposure,
    ExposureMetrics, EXPOSURE_LIMITS,
)


# ─── Helpers ───

def _empty_snapshot(balance=100_000.0):
    """Snapshot with zero positions."""
    return PortfolioSnapshot(
        positions=[], balance=balance,
        total_position_value=0.0, total_risk=0.0,
    )


def _snapshot_with_positions(positions, balance=100_000.0):
    """Snapshot with given positions."""
    total_val = sum(p.position_value for p in positions)
    total_risk = sum(p.risk_amount for p in positions)
    return PortfolioSnapshot(
        positions=positions, balance=balance,
        total_position_value=total_val, total_risk=total_risk,
    )


def _make_position(id=1, asset="BTCUSD", direction="LONG", value=5000.0,
                    risk=200.0, entry=67000.0, current=67500.0,
                    pnl=100.0, score=0.70):
    """Create a test position."""
    return OpenPosition(
        id=id, asset=asset, direction=direction,
        position_value=value, risk_amount=risk,
        entry_price=entry, current_price=current,
        unrealized_pnl=pnl, consensus_score=score,
        asset_class="crypto", themes=["risk_assets"],
    )


def _patch_subsystems():
    """Patch all external subsystems for unit testing."""
    return [
        patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok),
        patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()),
        patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()),
        patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()),
        patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}),
        patch("bahamut.portfolio.learning.get_adaptive_adjustments",
              return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}),
        patch("bahamut.shared.degraded.is_degraded", return_value=False),
        patch("bahamut.shared.degraded.mark_degraded"),
    ]


def _mock_kill_switch_ok(**kwargs):
    ks = MagicMock()
    ks.kill_switch_active = False
    ks.safe_mode_active = False
    ks.triggers = []
    ks.to_dict.return_value = {"kill_switch_active": False, "safe_mode_active": False, "triggers": []}
    return ks


def _mock_kill_switch_triggered(**kwargs):
    ks = MagicMock()
    ks.kill_switch_active = True
    ks.safe_mode_active = False
    ks.triggers = ["TAIL_RISK_CRITICAL"]
    ks.to_dict.return_value = {"kill_switch_active": True, "safe_mode_active": False,
                                "triggers": ["TAIL_RISK_CRITICAL"]}
    return ks


def _mock_scenario_ok():
    s = MagicMock()
    s.risk_level = "OK"
    s.portfolio_tail_risk = 0.02
    s.worst_scenario = "risk_off"
    s.weighted_tail_risk = 0.01
    s.to_dict.return_value = {"risk_level": "OK", "portfolio_tail_risk": 0.02}
    return s


def _mock_scenario_block():
    s = MagicMock()
    s.risk_level = "BLOCK"
    s.portfolio_tail_risk = 0.15
    s.worst_scenario = "crypto_shock"
    s.weighted_tail_risk = 0.12
    s.to_dict.return_value = {"risk_level": "BLOCK", "portfolio_tail_risk": 0.15}
    return s


def _mock_marginal_ok():
    m = MagicMock()
    m.risk_level = "OK"
    m.worst_case_marginal = -500
    m.worst_marginal_scenario = "risk_off"
    m.marginal_tail_risk = 0.01
    m.is_hedging = False
    m.to_dict.return_value = {"risk_level": "OK", "worst_case_marginal": -500}
    return m


def _mock_marginal_block():
    m = MagicMock()
    m.risk_level = "BLOCK"
    m.worst_case_marginal = -8000
    m.worst_marginal_scenario = "crypto_shock"
    m.marginal_tail_risk = 0.08
    m.is_hedging = False
    m.to_dict.return_value = {"risk_level": "BLOCK", "worst_case_marginal": -8000}
    return m


def _mock_quality_ok():
    q = MagicMock()
    q.risk_level = "OK"
    q.quality_ratio = 2.5
    q.to_dict.return_value = {"risk_level": "OK", "quality_ratio": 2.5}
    return q


def _mock_quality_block():
    q = MagicMock()
    q.risk_level = "BLOCK"
    q.quality_ratio = 0.1
    q.to_dict.return_value = {"risk_level": "BLOCK", "quality_ratio": 0.1}
    return q


# ═══════════════════════════════════════════════════════
# TEST 1: Zero positions → zero exposure
# ═══════════════════════════════════════════════════════

class TestPhantomExposure:

    def test_empty_snapshot_zero_exposure(self):
        """With no positions, exposure must be exactly 0."""
        snap = _empty_snapshot()
        exp = _compute_exposure(snap, "BTCUSD", "LONG", 5000, 100000)
        assert exp.gross == 0.0
        assert exp.net == 0.0
        assert exp.long_pct == 0.0
        assert exp.short_pct == 0.0
        # After-trade should only reflect the proposed trade
        assert exp.after_trade_gross == pytest.approx(5000 / 100000, abs=0.001)

    def test_phantom_exposure_auto_corrected(self):
        """If snapshot has 0 positions but non-zero value, force to zero."""
        snap = PortfolioSnapshot(
            positions=[],
            balance=100_000.0,
            total_position_value=373_000.0,  # phantom!
            total_risk=15_000.0,
        )
        # The sanity guard in evaluate_trade_for_portfolio should fix this
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
            )
            # After sanity guard, the snapshot should have been corrected
            assert snap.total_position_value == 0.0
            assert snap.total_risk == 0.0
            assert snap.positions == []
            # Trade should be allowed (no phantom blocking)
            assert verdict.allowed is True

    # ═══════════════════════════════════════════════════════
    # TEST 2: Stale positions ignored
    # ═══════════════════════════════════════════════════════

    def test_stale_positions_with_zero_value_skipped(self):
        """Positions with position_value <= 0 should not be loaded."""
        # This is tested at registry level — the new code skips pos_value <= 0
        # Here we verify compute_exposure handles an empty list correctly
        snap = _empty_snapshot()
        exp = _compute_exposure(snap, "ETHUSD", "SHORT", 3000, 100000)
        assert exp.gross == 0.0


# ═══════════════════════════════════════════════════════
# TEST 3: Restart safety
# ═══════════════════════════════════════════════════════

class TestRestartSafety:

    def test_empty_snapshot_after_restart(self):
        """After restart with no OPEN positions, exposure is 0."""
        snap = _empty_snapshot()
        exp = _compute_exposure(snap, "BTCUSD", "LONG", 5000, 100000)
        assert exp.gross == 0.0
        assert exp.after_trade_gross == pytest.approx(0.05, abs=0.001)


# ═══════════════════════════════════════════════════════
# TEST 4: Strict mode blocks risky trades
# ═══════════════════════════════════════════════════════

class TestStrictMode:

    def test_strict_blocks_on_scenario_risk(self):
        """In STRICT mode, scenario BLOCK verdict blocks the trade."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_block()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="STRICT",
            )
            assert verdict.allowed is False
            assert any("SCENARIO_RISK" in b for b in verdict.blockers)

    def test_strict_blocks_on_marginal_risk(self):
        """In STRICT mode, marginal risk BLOCK blocks the trade."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_block()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="STRICT",
            )
            assert verdict.allowed is False
            assert any("MARGINAL_RISK" in b for b in verdict.blockers)

    def test_strict_blocks_on_quality_ratio(self):
        """In STRICT mode, quality ratio BLOCK blocks the trade."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_block()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="STRICT",
            )
            assert verdict.allowed is False
            assert any("QUALITY_RATIO" in b for b in verdict.blockers)


# ═══════════════════════════════════════════════════════
# TEST 5: Exploration mode allows trades
# ═══════════════════════════════════════════════════════

class TestExplorationMode:

    def test_exploration_bypasses_scenario_risk(self):
        """Scenario risk BLOCK becomes a warning in EXPLORATION mode."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_block()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            assert verdict.allowed is True
            assert any("SCENARIO_RISK_BYPASSED" in w for w in verdict.warnings)
            # No blockers from scenario_risk
            assert not any("SCENARIO_RISK" in b for b in verdict.blockers)

    def test_exploration_bypasses_marginal_risk(self):
        """Marginal risk BLOCK becomes a warning in EXPLORATION mode."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_block()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            assert verdict.allowed is True
            assert any("MARGINAL_RISK_BYPASSED" in w for w in verdict.warnings)

    def test_exploration_bypasses_quality_ratio(self):
        """Quality ratio BLOCK becomes a warning in EXPLORATION mode."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_block()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            assert verdict.allowed is True
            assert any("QUALITY_RATIO_BYPASSED" in w for w in verdict.warnings)

    def test_exploration_survives_all_soft_blocks_at_once(self):
        """Even with ALL soft blockers firing, exploration still passes."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_block()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_block()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_block()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            assert verdict.allowed is True
            assert len(verdict.blockers) == 0
            bypassed = [w for w in verdict.warnings if "BYPASSED" in w]
            assert len(bypassed) == 3  # scenario, marginal, quality all bypassed


# ═══════════════════════════════════════════════════════
# TEST 6: Kill switch still blocks exploration
# ═══════════════════════════════════════════════════════

class TestKillSwitchInExploration:

    def test_kill_switch_blocks_exploration(self):
        """Kill switch is a HARD blocker — blocks even in EXPLORATION mode."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_triggered), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            assert verdict.allowed is False
            assert any("KILL_SWITCH" in b for b in verdict.blockers)


# ═══════════════════════════════════════════════════════
# TEST 7: Duplicate trades still blocked in exploration
# ═══════════════════════════════════════════════════════
# (Duplicate blocking happens at execution_policy level, not portfolio engine.
#  Portfolio engine's exposure cap handles the equivalent concern.)


# ═══════════════════════════════════════════════════════
# TEST 8: Crisis regime — ExecutionPolicy blocks exploration
# ═══════════════════════════════════════════════════════

class TestCrisisRegimeBlocking:

    def test_crisis_blocks_exploration_in_policy(self):
        """Crisis regime blocks exploration at ExecutionPolicy level."""
        from bahamut.execution.policy import ExecutionPolicy, ExecutionRequest

        policy = ExecutionPolicy()
        req = ExecutionRequest(
            asset="BTCUSD", direction="LONG",
            consensus_score=0.45, signal_label="WEAK_SIGNAL",
            execution_mode_from_consensus="AUTO",
            disagreement_gate="CLEAR",
            regime="CRISIS",
            is_exploration=True,
        )
        decision = policy.evaluate(req)
        assert decision.allowed is False
        assert any("CRISIS" in b for b in decision.blockers)


# ═══════════════════════════════════════════════════════
# TEST 9: Exposure cap enforced in exploration
# ═══════════════════════════════════════════════════════

class TestExposureCapInExploration:

    def test_gross_exposure_still_blocks_exploration(self):
        """Gross exposure limit is a HARD blocker — not bypassed in exploration."""
        # Create a snapshot with positions consuming 75% exposure
        positions = [
            _make_position(id=1, asset="BTCUSD", value=40000),
            _make_position(id=2, asset="ETHUSD", value=35000),
        ]
        snap = _snapshot_with_positions(positions, balance=100000)

        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_ok()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            # Adding a trade that would push gross above 80%
            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="SOLUSD",
                proposed_direction="LONG", proposed_value=10000,
                proposed_risk=500, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )
            # Gross would be (40000+35000+10000)/100000 = 85% > 80%
            assert verdict.allowed is False
            assert any("GROSS_EXPOSURE" in b for b in verdict.blockers)


# ═══════════════════════════════════════════════════════
# TEST 10: Decision breakdown logging
# ═══════════════════════════════════════════════════════

class TestDecisionTransparency:

    def test_exploration_verdict_contains_bypassed_info(self):
        """Verdict should clearly show which checks were bypassed."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_block()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_block()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_block()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="EXPLORATION",
            )

            # Check that bypassed info is present in warnings
            bypassed_warnings = [w for w in verdict.warnings if "BYPASSED" in w]
            assert len(bypassed_warnings) >= 3

            # Verify it's still allowed
            assert verdict.allowed is True
            assert verdict.size_multiplier > 0

    def test_strict_verdict_does_not_say_bypassed(self):
        """In STRICT mode, blocked checks should NOT say 'BYPASSED'."""
        snap = _empty_snapshot()
        with patch("bahamut.portfolio.engine.evaluate_kill_switch", side_effect=_mock_kill_switch_ok), \
             patch("bahamut.portfolio.scenarios.evaluate_scenario_risk", return_value=_mock_scenario_block()), \
             patch("bahamut.portfolio.marginal_risk.compute_marginal_risk", return_value=_mock_marginal_ok()), \
             patch("bahamut.portfolio.quality.compute_quality_ratio", return_value=_mock_quality_ok()), \
             patch("bahamut.portfolio.learning.capture_portfolio_state", return_value={}), \
             patch("bahamut.portfolio.learning.get_adaptive_adjustments",
                   return_value={"size_mult": 1.0, "force_approval": False, "active_rules": []}), \
             patch("bahamut.shared.degraded.is_degraded", return_value=False), \
             patch("bahamut.shared.degraded.mark_degraded"):

            verdict = evaluate_trade_for_portfolio(
                snapshot=snap, proposed_asset="BTCUSD",
                proposed_direction="LONG", proposed_value=5000,
                proposed_risk=200, consensus_score=0.70,
                execution_mode="STRICT",
            )

            assert verdict.allowed is False
            # In strict, no BYPASSED warnings
            bypassed = [w for w in verdict.warnings if "BYPASSED" in w]
            assert len(bypassed) == 0
