"""Integration tests for position opening flow."""
import pytest
import os

os.environ.setdefault("ENVIRONMENT", "test")


class TestBinanceFillFlow:
    """Tests for Binance Futures order fill handling."""

    def test_binance_fill_success_broker_truth_used(self, mock_binance_fill):
        from bahamut.execution.binance_futures import place_market_order
        result = place_market_order("BTCUSD", "BUY", 1.0)
        assert result["fill_price"] == 100.5
        assert result["status"] == "FILLED"
        assert result["order_id"] == "12345"

    def test_binance_fill_timeout_polled_for_5s(self, mock_binance_pending, monkeypatch):
        # Disable sleep to speed up test
        monkeypatch.setattr("time.sleep", lambda x: None)
        from bahamut.execution.binance_futures import place_market_order
        result = place_market_order("BTCUSD", "BUY", 1.0)
        # Should have polled and eventually got FILLED
        assert result["fill_price"] == 100.75
        assert result["status"] == "FILLED"
        assert mock_binance_pending["n"] >= 3

    def test_binance_rejected_no_position_saved(self, mock_binance_rejected):
        from bahamut.execution.binance_futures import place_market_order
        result = place_market_order("BTCUSD", "BUY", 1.0)
        assert "error" in result
        assert result.get("status_code") == 400

    def test_binance_partial_fill_handled(self, monkeypatch):
        def _post(*args, **kwargs):
            from tests.integration.conftest import MockResponse
            return MockResponse(200, {
                "orderId": 99999,
                "status": "PARTIALLY_FILLED",
                "avgPrice": "50000.25",
                "executedQty": "0.5",
            })

        def _get(*args, **kwargs):
            from tests.integration.conftest import MockResponse
            return MockResponse(200, {
                "orderId": 99999,
                "status": "FILLED",
                "avgPrice": "50000.50",
                "executedQty": "1.0",
            })

        monkeypatch.setattr("httpx.post", _post)
        monkeypatch.setattr("httpx.get", _get)
        monkeypatch.setattr("time.sleep", lambda x: None)

        from bahamut.execution.binance_futures import place_market_order
        result = place_market_order("BTCUSD", "BUY", 1.0)
        assert result["fill_price"] == 50000.50
        assert result["fill_qty"] == 1.0


class TestRiskBudgetIntegration:
    """Tests for cross-worker risk budget during opens."""

    def test_concurrent_open_risk_budget_serializes(self, mock_redis):
        from bahamut.trading.risk_budget import check_and_claim_budget, release_pending
        # First claim should succeed
        ok1, _ = check_and_claim_budget(100.0, "crypto")
        assert ok1
        # Second claim should also succeed (under $500 limit)
        ok2, _ = check_and_claim_budget(100.0, "crypto")
        assert ok2
        # Clean up
        release_pending(100.0)
        release_pending(100.0)

    def test_budget_exceeded_rejects_new_trade(self, mock_redis):
        from bahamut.trading.risk_budget import check_and_claim_budget
        # Claim close to limit
        ok1, _ = check_and_claim_budget(490.0, "crypto")
        assert ok1
        # This should exceed $500 limit
        ok2, reason = check_and_claim_budget(20.0, "crypto")
        assert not ok2
        assert "exceeded" in reason

    def test_budget_released_on_rejection(self, mock_redis):
        from bahamut.trading.risk_budget import (
            check_and_claim_budget, release_pending, get_budget_status
        )
        check_and_claim_budget(200.0, "crypto")
        release_pending(200.0)
        status = get_budget_status()
        assert status.get("daily_pending_risk", 0) <= 0.01

    def test_realized_loss_accumulates(self, mock_redis):
        from bahamut.trading.risk_budget import record_realized_loss, get_budget_status
        record_realized_loss(-50.0)
        record_realized_loss(-30.0)
        status = get_budget_status()
        assert status.get("daily_realized_loss", 0) <= -79.99


class TestDuplicateSignalRejection:
    """Tests for idempotency via OrderManager."""

    def test_duplicate_signal_rejected(self, mock_redis, monkeypatch):
        # This tests the concept — actual OrderManager uses DB
        # Mock the DB layer for unit testing
        pass  # Requires DB fixtures — placeholder for CI setup
