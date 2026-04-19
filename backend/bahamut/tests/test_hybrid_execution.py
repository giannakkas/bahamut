"""
Bahamut.AI — Hybrid Execution Tests

Tests for:
  - Early execution evaluator conditions
  - Standard execution unchanged
  - Max early trades limit
  - Risk multiplier applied
  - DB fields stored correctly
  - No production contamination

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_hybrid_execution.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from bahamut.trading.engine import (
    evaluate_early_execution, TrainingPosition, TrainingTrade,
    EARLY_CONFIG,
)


def _good_indicators():
    """Indicators that pass all early execution checks."""
    return {
        "rsi_14": 55,
        "rsi": 55,
        "ema_alignment": "bullish_stack",
    }


class TestEarlyExecutionEvaluator:
    """Test evaluate_early_execution() gate conditions."""

    @pytest.fixture(autouse=True)
    def _mock(self):
        with patch("bahamut.trading.engine._load_positions", return_value=[]):
            with patch("bahamut.trading.engine._check_scan_consistency", return_value=True):
                yield

    def test_all_conditions_met(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="TREND",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is True
        assert result["confidence"] == 92
        assert result["risk_multiplier"] == 0.5

    def test_score_below_90_rejected(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=85, regime="TREND",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False
        assert any("Score 85" in r for r in result["failed_conditions"])

    def test_transition_regime_rejected(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="transition",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False
        assert any("unstable" in r.lower() for r in result["failed_conditions"])

    def test_crash_regime_rejected(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="crash",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False

    def test_range_regime_rejected(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="RANGE",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False
        assert any("not strong enough" in r for r in result["failed_conditions"])

    def test_rsi_too_high_rejected(self):
        ind = _good_indicators()
        ind["rsi_14"] = 80
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="TREND",
            direction="LONG", indicators=ind,
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False
        assert any("RSI extreme" in r for r in result["failed_conditions"])

    def test_rsi_too_low_rejected(self):
        ind = _good_indicators()
        ind["rsi_14"] = 20
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="TREND",
            direction="LONG", indicators=ind,
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False

    def test_distance_too_far_rejected(self):
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="TREND",
            direction="LONG", indicators=_good_indicators(),
            distance_to_trigger="2.5%",
        )
        assert result["eligible"] is False
        assert any("Distance" in r for r in result["failed_conditions"])

    def test_ema_misalignment_rejected(self):
        ind = _good_indicators()
        ind["ema_alignment"] = "bearish"
        result = evaluate_early_execution(
            asset="BTCUSD", readiness_score=92, regime="TREND",
            direction="LONG", indicators=ind,
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is False
        assert any("EMA alignment weak" in r for r in result["failed_conditions"])

    def test_short_with_bearish_ema_passes(self):
        ind = _good_indicators()
        ind["ema_alignment"] = "bearish_stack"
        result = evaluate_early_execution(
            asset="EURUSD", readiness_score=92, regime="TREND",
            direction="SHORT", indicators=ind,
            distance_to_trigger="0.5%",
        )
        assert result["eligible"] is True

    def test_existing_position_blocked(self):
        pos = TrainingPosition(
            position_id="x", asset="BTCUSD", asset_class="crypto",
            strategy="v5_base", direction="LONG", entry_price=68000,
            stop_price=66000, tp_price=72000, size=0.1, risk_amount=200,
            entry_time="2025-01-01T00:00:00", max_hold_bars=30,
        )
        with patch("bahamut.trading.engine._load_positions", return_value=[pos]):
            result = evaluate_early_execution(
                asset="BTCUSD", readiness_score=92, regime="TREND",
                direction="LONG", indicators=_good_indicators(),
                distance_to_trigger="0.5%",
            )
        assert result["eligible"] is False
        assert any("Already holding" in r for r in result["failed_conditions"])

    def test_early_cap_reached(self):
        early_pos = TrainingPosition(
            position_id="e1", asset="ETHUSD", asset_class="crypto",
            strategy="v5_base", direction="LONG", entry_price=3000,
            stop_price=2900, tp_price=3200, size=0.5, risk_amount=100,
            entry_time="2025-01-01T00:00:00", max_hold_bars=30,
            execution_type="early",
        )
        with patch("bahamut.trading.engine._load_positions", return_value=[early_pos] * 3):
            result = evaluate_early_execution(
                asset="BTCUSD", readiness_score=92, regime="TREND",
                direction="LONG", indicators=_good_indicators(),
                distance_to_trigger="0.5%",
            )
        assert result["eligible"] is False
        assert any("cap" in r.lower() for r in result["failed_conditions"])


class TestScanConsistency:
    def test_inconsistent_direction_blocked(self):
        with patch("bahamut.trading.engine._load_positions", return_value=[]):
            with patch("bahamut.trading.engine._check_scan_consistency", return_value=False):
                result = evaluate_early_execution(
                    asset="BTCUSD", readiness_score=92, regime="TREND",
                    direction="LONG", indicators=_good_indicators(),
                    distance_to_trigger="0.5%",
                )
        assert result["eligible"] is False
        assert any("consistent" in r.lower() for r in result["failed_conditions"])


class TestDataclassFields:
    def test_position_has_execution_fields(self):
        p = TrainingPosition(
            position_id="x", asset="BTC", asset_class="crypto",
            strategy="v5", direction="LONG", entry_price=100,
            stop_price=95, tp_price=110, size=1, risk_amount=5,
            entry_time="t", execution_type="early",
            confidence_score=92.0, trigger_reason="early_signal",
        )
        assert p.execution_type == "early"
        assert p.confidence_score == 92.0
        assert p.trigger_reason == "early_signal"

    def test_trade_has_execution_fields(self):
        t = TrainingTrade(
            trade_id="x", position_id="y", asset="BTC",
            asset_class="crypto", strategy="v5", direction="LONG",
            entry_price=100, exit_price=110, stop_price=95,
            tp_price=110, size=1, risk_amount=5, pnl=10,
            pnl_pct=2.0, entry_time="t1", exit_time="t2",
            exit_reason="TP", bars_held=5,
            execution_type="early", confidence_score=92.0,
            trigger_reason="early_signal",
        )
        assert t.execution_type == "early"
        assert t.confidence_score == 92.0

    def test_defaults_are_standard(self):
        p = TrainingPosition(
            position_id="x", asset="BTC", asset_class="crypto",
            strategy="v5", direction="LONG", entry_price=100,
            stop_price=95, tp_price=110, size=1, risk_amount=5,
            entry_time="t",
        )
        assert p.execution_type == "standard"
        assert p.trigger_reason == "4h_close"
        assert p.confidence_score == 0.0


class TestPendingSignalFields:
    def test_pending_signal_has_execution_fields(self):
        from bahamut.trading.selector import PendingSignal
        sig = PendingSignal(
            asset="BTC", asset_class="crypto", strategy="v5",
            direction="LONG", readiness_score=92, regime="TREND",
            entry_price=100, sl_pct=0.03, tp_pct=0.06,
            max_hold_bars=30, reasons=["test"],
            execution_type="early", confidence_score=92.0,
            trigger_reason="early_signal", risk_multiplier=0.5,
        )
        assert sig.execution_type == "early"
        assert sig.risk_multiplier == 0.5

    def test_pending_signal_defaults(self):
        from bahamut.trading.selector import PendingSignal
        sig = PendingSignal(
            asset="BTC", asset_class="crypto", strategy="v5",
            direction="LONG", readiness_score=80, regime="TREND",
            entry_price=100, sl_pct=0.03, tp_pct=0.06,
            max_hold_bars=30, reasons=[],
        )
        assert sig.execution_type == "standard"
        assert sig.risk_multiplier == 1.0
        assert sig.trigger_reason == "4h_close"


class TestIsolation:
    def test_no_production_engine_import(self):
        import inspect
        from bahamut.trading import engine
        source = inspect.getsource(engine)
        # Check no actual import of production ExecutionEngine
        assert "from bahamut.execution" not in source
        assert "import ExecutionEngine" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
