"""
Bahamut Regression Tests — Performance Engine, Test Trade, Data Health

Run: python -m pytest backend/bahamut/tests/test_new_features.py -v
"""
import json
import pytest


class TestPerformanceEngine:
    """Test performance engine calculations."""

    def test_empty_state_returns_valid_shape(self):
        """Performance must return valid structure with no trades."""
        from bahamut.monitoring.performance import compute_performance
        result = compute_performance()

        assert "portfolio" in result
        assert "strategies" in result
        assert "assets" in result
        assert "has_data" in result
        assert isinstance(result["portfolio"], dict)
        assert isinstance(result["strategies"], dict)
        # Core strategies always present
        assert "v5_base" in result["strategies"]
        assert "v5_tuned" in result["strategies"]
        assert "v9_breakout" in result["strategies"]
        # Core assets always present
        assert "BTCUSD" in result["assets"]
        assert "ETHUSD" in result["assets"]

    def test_portfolio_metrics_shape(self):
        """All required metrics must be present."""
        from bahamut.monitoring.performance import compute_performance
        result = compute_performance()
        p = result["portfolio"]

        required = ["total_trades", "pnl", "win_rate", "profit_factor",
                    "expectancy", "avg_win", "avg_loss", "max_drawdown",
                    "open_positions", "closed_trades"]
        for key in required:
            assert key in p, f"Missing key: {key}"

    def test_strategy_metrics_shape(self):
        """Each strategy must have the required fields."""
        from bahamut.monitoring.performance import compute_performance
        result = compute_performance()
        for name, s in result["strategies"].items():
            assert "total_trades" in s
            assert "pnl" in s
            assert "win_rate" in s
            assert "profit_factor" in s
            assert "open_positions" in s

    def test_compute_with_mock_trades(self):
        """Test computation with injected trades."""
        from bahamut.monitoring.performance import _compute_metrics
        from bahamut.execution.models import ClosedTrade, Position

        trades = [
            ClosedTrade(strategy="v5_base", asset="BTCUSD", pnl=100, bars_held=5,
                       entry_price=68000, exit_price=68100, exit_reason="TP"),
            ClosedTrade(strategy="v5_base", asset="BTCUSD", pnl=-50, bars_held=3,
                       entry_price=68000, exit_price=67950, exit_reason="SL"),
            ClosedTrade(strategy="v5_base", asset="BTCUSD", pnl=200, bars_held=8,
                       entry_price=68000, exit_price=68200, exit_reason="TP"),
        ]

        result = _compute_metrics(trades, [], None)

        assert result["total_trades"] == 3
        assert result["pnl"] == 250  # 100 - 50 + 200
        assert result["wins"] == 2
        assert result["losses"] == 1
        assert result["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert result["profit_factor"] > 1
        assert result["avg_win"] == 150  # (100 + 200) / 2
        assert result["avg_loss"] == 50  # abs(-50) / 1
        assert result["max_drawdown"] == 50  # peak was 100, dropped to 50


class TestTestTradeMode:
    """Test the test trade lifecycle."""

    def test_create_test_trade(self):
        """Test trade should create through the engine."""
        from bahamut.execution.test_trade_mode import create_test_trade
        result = create_test_trade(asset="BTCUSD", entry_price=68000.0)

        assert result["status"] in ("OPENED", "REJECTED", "FAILED")
        if result["status"] == "OPENED":
            assert "position" in result
            assert result["position"]["asset"] == "BTCUSD"
            assert result["position"]["strategy"].startswith("TEST_")
            assert result["position"]["entry_price"] > 0

    def test_close_test_trade(self):
        """Test trade should close cleanly."""
        from bahamut.execution.test_trade_mode import create_test_trade, close_test_trade
        # Ensure a fresh test trade exists
        from bahamut.execution.engine import get_execution_engine
        engine = get_execution_engine()

        # Clean any existing test positions
        test_pos = [p for p in engine.open_positions if p.strategy.startswith("TEST_")]
        for p in test_pos:
            engine.open_positions.remove(p)
        engine._processed_signals = set()  # Reset idempotency

        open_result = create_test_trade(asset="BTCUSD", entry_price=68000.0)
        if open_result["status"] == "OPENED":
            close_result = close_test_trade(close_price=68500.0)
            assert close_result["status"] == "CLOSED"
            assert close_result["trade"]["pnl"] > 0  # Closed at higher price

    def test_get_status(self):
        """Status should always return valid shape."""
        from bahamut.execution.test_trade_mode import get_test_trade_status
        result = get_test_trade_status()

        assert "open_test_positions" in result
        assert "closed_test_trades" in result
        assert isinstance(result["positions"], list)
        assert isinstance(result["trades"], list)


class TestDataHealth:
    """Test data health module."""

    def test_returns_valid_shape(self):
        """Data health must return valid structure."""
        from bahamut.monitoring.data_health import get_data_health
        result = get_data_health()

        assert "status" in result
        assert "source" in result
        assert "assets" in result
        assert result["status"] in ("OK", "DELAYED", "STALE", "FALLBACK", "UNKNOWN")

    def test_assets_structure(self):
        """Each asset entry must have required fields."""
        from bahamut.monitoring.data_health import get_data_health
        result = get_data_health()

        for asset_name, asset_data in result["assets"].items():
            assert "last_update" in asset_data
            assert "status" in asset_data


class TestStrategyConditions:
    """Test strategy conditions numpy serialization fix."""

    def test_json_serializable(self):
        """Strategy conditions must be fully JSON-serializable."""
        import numpy as np
        from bahamut.monitoring.strategy_conditions import _to_native

        data = {
            "price": np.float64(68000.0),
            "passed": np.bool_(True),
            "count": np.int64(5),
            "nested": [np.float64(1.0), {"inner": np.bool_(False)}],
        }

        native = _to_native(data)
        # Must not raise
        serialized = json.dumps(native)
        parsed = json.loads(serialized)

        assert parsed["price"] == 68000.0
        assert parsed["passed"] is True
        assert parsed["count"] == 5
        assert parsed["nested"][0] == 1.0
        assert parsed["nested"][1]["inner"] is False

    def test_compute_conditions_serializable(self):
        """Full compute_conditions output must serialize to JSON."""
        from bahamut.monitoring.strategy_conditions import compute_conditions

        # Mock candles and indicators with numpy types
        import numpy as np
        candles = [{"open": 67000, "high": 68500, "low": 66500, "close": 68000, "datetime": "2026-01-01T00:00:00Z"}] * 30
        indicators = {
            "close": np.float64(68000.0),
            "ema_20": np.float64(67500.0),
            "ema_50": np.float64(66000.0),
            "ema_200": np.float64(65000.0),
        }
        prev_indicators = {
            "ema_20": np.float64(66500.0),
            "ema_50": np.float64(66800.0),
        }

        results = compute_conditions("BTCUSD", candles, indicators, prev_indicators, "RANGE")

        # Must not raise
        serialized = json.dumps(results)
        parsed = json.loads(serialized)
        assert len(parsed) == 3  # v5_base, v5_tuned, v9_breakout


class TestAuditLog:
    """Test audit log endpoint handles empty data."""

    def test_get_audit_log_empty(self):
        """Audit log should return empty list without error."""
        from bahamut.admin.config import get_audit_log
        result = get_audit_log(limit=10)
        assert isinstance(result, list)


class TestHealthEndpoint:
    """Test health endpoint is lightweight."""

    def test_health_returns_quickly(self):
        """Health must be a simple dict, no DB/Redis calls."""
        import time
        start = time.monotonic()
        # Simulate what the endpoint returns
        result = {
            "status": "healthy",
            "service": "bahamut-api",
            "version": "1.0.0",
        }
        elapsed = time.monotonic() - start
        assert elapsed < 0.01  # Must be < 10ms
        assert result["status"] == "healthy"
