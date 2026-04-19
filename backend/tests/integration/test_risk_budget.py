"""Integration tests for cross-worker risk budget."""
import pytest
import os

os.environ.setdefault("ENVIRONMENT", "test")


class TestRiskBudgetAtomicity:
    """Tests for atomic risk budget enforcement."""

    def test_budget_tracks_pending_risk(self, mock_redis):
        from bahamut.trading.risk_budget import check_and_claim_budget, get_budget_status
        ok, _ = check_and_claim_budget(150.0, "crypto")
        assert ok
        status = get_budget_status()
        assert status["daily_pending_risk"] >= 149.99

    def test_budget_exceeded_rejects(self, mock_redis):
        from bahamut.trading.risk_budget import check_and_claim_budget
        # Fill to near limit
        check_and_claim_budget(480.0, "crypto")
        # This should fail ($480 + $30 > $500)
        ok, reason = check_and_claim_budget(30.0, "crypto")
        assert not ok
        assert "exceeded" in reason

    def test_budget_rollback_on_rejection(self, mock_redis):
        from bahamut.trading.risk_budget import check_and_claim_budget, get_budget_status
        check_and_claim_budget(480.0, "crypto")
        # Attempt that fails
        check_and_claim_budget(30.0, "crypto")
        # Budget should NOT include the rejected 30
        status = get_budget_status()
        assert status["daily_pending_risk"] < 490

    def test_release_reduces_pending(self, mock_redis):
        from bahamut.trading.risk_budget import (
            check_and_claim_budget, release_pending, get_budget_status
        )
        check_and_claim_budget(200.0, "crypto")
        release_pending(200.0)
        status = get_budget_status()
        assert abs(status["daily_pending_risk"]) < 1.0

    def test_realized_loss_tracked_only_for_losses(self, mock_redis):
        from bahamut.trading.risk_budget import record_realized_loss, get_budget_status
        record_realized_loss(100.0)   # profit — should be ignored
        record_realized_loss(-25.0)   # loss — should be tracked
        status = get_budget_status()
        assert status["daily_realized_loss"] <= -24.99

    def test_redis_unavailable_fails_closed(self, monkeypatch):
        """No Redis = no trading (fail closed)."""
        monkeypatch.setattr("redis.from_url", lambda *a, **kw: None)
        from bahamut.trading.risk_budget import check_and_claim_budget
        ok, reason = check_and_claim_budget(10.0, "crypto")
        assert not ok
        assert "unavailable" in reason
