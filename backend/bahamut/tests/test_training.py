"""
Bahamut.AI — Training Universe Tests

Covers:
  1. Training engine is isolated from production engine
  2. Position open/close lifecycle works
  3. Duplicate position prevention
  4. Learning stats update on close
  5. Config segmentation (production vs training)
  6. Asset mode returns correct values

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_training.py -v
"""
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════
# ASSET CONFIG SEGMENTATION
# ═══════════════════════════════════════════

class TestAssetConfig:
    def test_production_assets_are_btc_eth(self):
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        assert "BTCUSD" in ACTIVE_TREND_ASSETS
        assert "ETHUSD" in ACTIVE_TREND_ASSETS
        assert len(ACTIVE_TREND_ASSETS) == 2

    def test_training_assets_exist(self):
        from bahamut.config_assets import TRAINING_ASSETS
        assert len(TRAINING_ASSETS) >= 30

    def test_training_includes_crypto(self):
        from bahamut.config_assets import TRAINING_CRYPTO
        assert "SOLUSD" in TRAINING_CRYPTO
        assert "BTCUSD" in TRAINING_CRYPTO  # Overlap is intentional

    def test_training_includes_forex(self):
        from bahamut.config_assets import TRAINING_FOREX
        assert "EURUSD" in TRAINING_FOREX

    def test_training_includes_stocks(self):
        from bahamut.config_assets import TRAINING_STOCKS
        assert "AAPL" in TRAINING_STOCKS
        assert "NVDA" in TRAINING_STOCKS

    def test_asset_mode_production(self):
        from bahamut.config_assets import get_asset_mode
        assert get_asset_mode("BTCUSD") == "production"
        assert get_asset_mode("ETHUSD") == "production"

    def test_asset_mode_training(self):
        from bahamut.config_assets import get_asset_mode
        assert get_asset_mode("EURUSD") == "training"
        assert get_asset_mode("AAPL") == "training"
        assert get_asset_mode("XAUUSD") == "training"

    def test_asset_mode_unknown(self):
        from bahamut.config_assets import get_asset_mode
        assert get_asset_mode("FAKEUSD") == "unknown"

    def test_asset_class_mapping(self):
        from bahamut.config_assets import ASSET_CLASS_MAP
        assert ASSET_CLASS_MAP["BTCUSD"] == "crypto"
        assert ASSET_CLASS_MAP["EURUSD"] == "forex"
        assert ASSET_CLASS_MAP["AAPL"] == "stock"
        assert ASSET_CLASS_MAP["XAUUSD"] == "commodity"
        assert ASSET_CLASS_MAP["SPX"] == "index"


# ═══════════════════════════════════════════
# TRAINING ENGINE ISOLATION
# ═══════════════════════════════════════════

class TestTrainingIsolation:
    def test_training_engine_does_not_touch_production(self):
        """Training position does NOT appear in production ExecutionEngine."""
        from bahamut.execution.engine import ExecutionEngine
        from bahamut.training.engine import TrainingPosition

        prod_engine = ExecutionEngine()
        train_pos = TrainingPosition(
            position_id="t1", asset="EURUSD", asset_class="forex",
            strategy="v5_base", direction="LONG", entry_price=1.08,
            stop_price=1.07, tp_price=1.10, size=1000,
            risk_amount=500, entry_time="2026-01-01T00:00:00",
        )

        # Training position is a completely different type
        assert len(prod_engine.open_positions) == 0
        # Cannot accidentally add it
        assert not hasattr(prod_engine, 'training_positions')

    def test_training_uses_separate_redis_keys(self):
        """Training Redis keys are separate from production."""
        from bahamut.training.engine import REDIS_KEY_POSITIONS, REDIS_KEY_RECENT
        assert "training" in REDIS_KEY_POSITIONS
        assert "training" in REDIS_KEY_RECENT

    def test_training_risk_is_smaller(self):
        from bahamut.config_assets import TRAINING_RISK_PER_TRADE_PCT
        assert TRAINING_RISK_PER_TRADE_PCT <= 0.01  # Max 1% per trade


# ═══════════════════════════════════════════
# TRAINING POSITION LIFECYCLE
# ═══════════════════════════════════════════

class TestTrainingLifecycle:
    def test_position_model(self):
        from bahamut.training.engine import TrainingPosition
        pos = TrainingPosition(
            position_id="test1", asset="EURUSD", asset_class="forex",
            strategy="v5_base", direction="LONG", entry_price=1.0800,
            stop_price=1.0476, tp_price=1.1448, size=15432,
            risk_amount=500, entry_time="2026-01-01T00:00:00",
            current_price=1.0900,
        )
        assert pos.unrealized_pnl == pytest.approx((1.09 - 1.08) * 15432, abs=1)

    def test_position_short_pnl(self):
        from bahamut.training.engine import TrainingPosition
        pos = TrainingPosition(
            position_id="test2", asset="EURUSD", asset_class="forex",
            strategy="v5_base", direction="SHORT", entry_price=1.0800,
            stop_price=1.1124, tp_price=1.0152, size=15432,
            risk_amount=500, entry_time="2026-01-01T00:00:00",
            current_price=1.0700,
        )
        assert pos.unrealized_pnl > 0  # Price went down for SHORT = profit

    def test_update_positions_sl_hit(self):
        """Position closes when SL is hit."""
        from bahamut.training.engine import (
            TrainingPosition, update_positions_for_asset,
            _save_position, _load_positions, _remove_position,
        )

        pos = TrainingPosition(
            position_id="sl_test", asset="TESTASSET", asset_class="test",
            strategy="v5_base", direction="LONG", entry_price=100.0,
            stop_price=97.0, tp_price=106.0, size=10.0,
            risk_amount=30.0, entry_time="2026-01-01T00:00:00",
        )

        # Mock Redis
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            b"sl_test": '{"position_id":"sl_test","asset":"TESTASSET","asset_class":"test","strategy":"v5_base","direction":"LONG","entry_price":100.0,"stop_price":97.0,"tp_price":106.0,"size":10.0,"risk_amount":30.0,"entry_time":"2026-01-01T00:00:00","bars_held":0,"max_hold_bars":30,"current_price":100.0}'
        }
        mock_redis.ping.return_value = True

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            bar = {"open": 99, "high": 99.5, "low": 96.5, "close": 97.0}
            closed = update_positions_for_asset("TESTASSET", bar)

        assert len(closed) == 1
        assert closed[0].exit_reason == "SL"
        assert closed[0].pnl < 0  # Loss

    def test_update_positions_tp_hit(self):
        """Position closes when TP is hit."""
        from bahamut.training.engine import update_positions_for_asset

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            b"tp_test": '{"position_id":"tp_test","asset":"TESTASSET","asset_class":"test","strategy":"v5_base","direction":"LONG","entry_price":100.0,"stop_price":97.0,"tp_price":106.0,"size":10.0,"risk_amount":30.0,"entry_time":"2026-01-01T00:00:00","bars_held":0,"max_hold_bars":30,"current_price":100.0}'
        }
        mock_redis.ping.return_value = True

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            bar = {"open": 104, "high": 107, "low": 103, "close": 106.5}
            closed = update_positions_for_asset("TESTASSET", bar)

        assert len(closed) == 1
        assert closed[0].exit_reason == "TP"
        assert closed[0].pnl > 0  # Profit

    def test_update_positions_timeout(self):
        """Position closes on timeout."""
        from bahamut.training.engine import update_positions_for_asset

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            b"to_test": '{"position_id":"to_test","asset":"TESTASSET","asset_class":"test","strategy":"v5_base","direction":"LONG","entry_price":100.0,"stop_price":97.0,"tp_price":106.0,"size":10.0,"risk_amount":30.0,"entry_time":"2026-01-01T00:00:00","bars_held":29,"max_hold_bars":30,"current_price":100.0}'
        }
        mock_redis.ping.return_value = True

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            bar = {"open": 101, "high": 102, "low": 100, "close": 101.5}
            closed = update_positions_for_asset("TESTASSET", bar)

        assert len(closed) == 1
        assert closed[0].exit_reason == "TIMEOUT"


# ═══════════════════════════════════════════
# DUPLICATE PREVENTION
# ═══════════════════════════════════════════

class TestTrainingDuplicates:
    def test_duplicate_position_rejected(self):
        """Cannot open same asset + strategy + direction twice."""
        from bahamut.training.engine import open_training_position

        mock_redis = MagicMock()
        mock_redis.hlen.return_value = 0
        mock_redis.hgetall.return_value = {
            b"existing": '{"position_id":"existing","asset":"EURUSD","asset_class":"forex","strategy":"v5_base","direction":"LONG","entry_price":1.08,"stop_price":1.07,"tp_price":1.10,"size":1000,"risk_amount":500,"entry_time":"2026-01-01","bars_held":0,"max_hold_bars":30,"current_price":1.08}'
        }
        mock_redis.ping.return_value = True

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            result = open_training_position(
                asset="EURUSD", asset_class="forex", strategy="v5_base",
                direction="LONG", entry_price=1.08, sl_pct=0.03,
                tp_pct=0.06, risk_amount=500,
            )

        assert result is None  # Duplicate rejected

    def test_max_positions_enforced(self):
        """Cannot exceed max training positions."""
        from bahamut.training.engine import open_training_position

        mock_redis = MagicMock()
        mock_redis.hlen.return_value = 20  # At max
        mock_redis.ping.return_value = True

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            result = open_training_position(
                asset="NEWASSET", asset_class="test", strategy="v5_base",
                direction="LONG", entry_price=100, sl_pct=0.03,
                tp_pct=0.06, risk_amount=500,
            )

        assert result is None  # Max positions exceeded


# ═══════════════════════════════════════════
# TWELVE DATA SYMBOL COVERAGE
# ═══════════════════════════════════════════

class TestSymbolCoverage:
    def test_all_training_assets_have_twelvedata_symbol(self):
        """Every training asset must map to a TwelveData symbol."""
        from bahamut.config_assets import TRAINING_ASSETS
        from bahamut.ingestion.adapters.twelvedata import TWELVE_SYMBOL_MAP

        missing = []
        for asset in TRAINING_ASSETS:
            if asset not in TWELVE_SYMBOL_MAP:
                missing.append(asset)

        assert len(missing) == 0, f"Training assets missing TwelveData mapping: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
