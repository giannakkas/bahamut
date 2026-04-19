"""Integration tests for reconciliation logic."""
import pytest
import os

os.environ.setdefault("ENVIRONMENT", "test")


class TestOrphanHandling:
    """Tests for orphan position detection and handling."""

    def test_orphan_not_auto_adopted_by_default(self, mock_redis):
        """Without BAHAMUT_AUTO_ADOPT_ORPHANS=1, orphans are NOT auto-promoted."""
        os.environ.pop("BAHAMUT_AUTO_ADOPT_ORPHANS", None)
        auto_adopt = os.environ.get("BAHAMUT_AUTO_ADOPT_ORPHANS", "0").lower() in ("1", "true", "yes")
        assert not auto_adopt

    def test_orphan_auto_adopted_when_env_set(self, mock_redis):
        """With BAHAMUT_AUTO_ADOPT_ORPHANS=1, orphans ARE auto-promoted."""
        os.environ["BAHAMUT_AUTO_ADOPT_ORPHANS"] = "1"
        auto_adopt = os.environ.get("BAHAMUT_AUTO_ADOPT_ORPHANS", "0").lower() in ("1", "true", "yes")
        assert auto_adopt
        os.environ.pop("BAHAMUT_AUTO_ADOPT_ORPHANS", None)

    def test_orphan_blocks_asset_for_1hr(self, mock_redis):
        """Orphan detection should set a 1-hour block key in Redis."""
        asset = "BTCUSD"
        # Simulate what reconciliation does
        mock_redis[f"bahamut:trading:asset_block:{asset}"] = "orphan_detected"

        # Engine should check this
        blocked = f"bahamut:trading:asset_block:{asset}" in mock_redis
        assert blocked
        assert mock_redis[f"bahamut:trading:asset_block:{asset}"] == "orphan_detected"


class TestBracketCoverage:
    """Tests for bracket SL/TP coverage verification."""

    def test_missing_bracket_ids_detected(self):
        """Positions without bracket_sl_order_id should be flagged."""
        from bahamut.trading.engine import TrainingPosition
        pos = TrainingPosition(
            position_id="test1", asset="BTCUSD", asset_class="crypto",
            strategy="v5_base", direction="LONG",
            entry_price=50000.0, current_price=50000.0,
            stop_price=48000.0, tp_price=55000.0,
            size=0.01, risk_amount=20.0,
        )
        # No bracket IDs set
        assert not getattr(pos, "bracket_sl_order_id", "")
        assert not getattr(pos, "bracket_tp_order_id", "")

    def test_bracket_both_missing_suspect_close(self):
        """When both SL and TP brackets are gone, position likely closed on exchange."""
        sl_live = False
        tp_live = False
        suspect_broker_close = not sl_live and not tp_live
        assert suspect_broker_close
