"""
Bahamut.AI — Learning Pipeline End-to-End Tests

Verifies the complete data flow:
  training trade closes → _feed_learning → strategy stats → trust score
  → learning progress → agent leaderboard → adaptive risk

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_learning_pipeline.py -v
"""
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════
# 1. LEARNING PROGRESS FROM TRAINING TRADES
# ═══════════════════════════════════════════

class TestLearningProgress:
    def test_zero_trades_warming_up(self):
        """No trades → warming_up status."""
        with patch("bahamut.db.query.run_query_one", return_value={"cnt": 0}):
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["status"] == "warming_up"
        assert lp["progress"] == 0
        assert lp["trust_ready"] is False
        assert lp["adaptive_ready"] is False

    def test_five_trades_warming_up(self):
        with patch("bahamut.db.query.run_query_one") as mock:
            mock.side_effect = [
                {"cnt": 5},
                {"total": 5, "wins": 3, "total_pnl": 150.0, "strats": 2, "classes": 2},
            ]
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["status"] == "warming_up"
        assert lp["closed_trades"] == 5
        assert lp["trust_ready"] is False

    def test_ten_trades_trust_ready(self):
        with patch("bahamut.db.query.run_query_one") as mock:
            mock.side_effect = [
                {"cnt": 10},
                {"total": 10, "wins": 6, "total_pnl": 300.0, "strats": 3, "classes": 3},
            ]
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["status"] == "learning"
        assert lp["trust_ready"] is True
        assert lp["adaptive_ready"] is False

    def test_25_trades_adaptive_ready(self):
        with patch("bahamut.db.query.run_query_one") as mock:
            mock.side_effect = [
                {"cnt": 25},
                {"total": 25, "wins": 15, "total_pnl": 800.0, "strats": 3, "classes": 4},
            ]
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["status"] == "learning"
        assert lp["trust_ready"] is True
        assert lp["adaptive_ready"] is True

    def test_100_trades_fully_trained(self):
        with patch("bahamut.db.query.run_query_one") as mock:
            mock.side_effect = [
                {"cnt": 100},
                {"total": 100, "wins": 58, "total_pnl": 2400.0, "strats": 3, "classes": 5},
            ]
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["status"] == "ready"
        assert lp["progress"] == 100

    def test_milestones_advance(self):
        with patch("bahamut.db.query.run_query_one") as mock:
            mock.side_effect = [
                {"cnt": 30},
                {"total": 30, "wins": 18, "total_pnl": 900.0, "strats": 3, "classes": 4},
            ]
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        reached = [m for m in lp["milestones"] if m["reached"]]
        not_reached = [m for m in lp["milestones"] if not m["reached"]]
        assert len(reached) == 3  # 1, 10, 25
        assert len(not_reached) == 2  # 50, 100
        assert "50" not in lp["next_milestone"] or "more" in lp["next_milestone"]

    def test_data_source_field(self):
        with patch("bahamut.db.query.run_query_one", return_value={"cnt": 0}):
            from bahamut.intelligence.learning_progress import get_learning_progress
            lp = get_learning_progress()
        assert lp["data_source"] in ("training_trades", "redis_stats")


# ═══════════════════════════════════════════
# 2. TRUST SCORES — PROVISIONAL VS COMPUTED
# ═══════════════════════════════════════════

class TestTrustScores:
    def test_provisional_below_threshold(self):
        """Below MIN_SAMPLES → trust is provisional 0.5."""
        from bahamut.intelligence.agent_performance import get_strategy_trust
        with patch("bahamut.db.query.run_query_one", return_value={"total": 5, "wins": 3, "losses": 2, "avg_pnl": 10, "gross_profit": 50, "gross_loss": 20}):
            with patch("bahamut.db.query.run_query", return_value=[]):
                trust = get_strategy_trust("v5_base")
        assert trust["provisional"] is True
        assert trust["trust_score"] == 0.5
        assert trust["trust_label"] == "provisional"

    def test_computed_above_threshold(self):
        """Above MIN_SAMPLES → trust computed from real outcomes."""
        from bahamut.intelligence.agent_performance import get_strategy_trust
        with patch("bahamut.db.query.run_query_one", return_value={"total": 15, "wins": 10, "losses": 5, "avg_pnl": 20, "gross_profit": 300, "gross_loss": 100}):
            recent = [{"pnl": 10 + i} for i in range(10)]
            with patch("bahamut.db.query.run_query", return_value=recent):
                trust = get_strategy_trust("v5_base")
        assert trust["provisional"] is False
        assert trust["trust_score"] > 0.5  # Should be good with 67% WR + PF 3.0
        assert trust["trust_label"] in ("high", "moderate")

    def test_trust_label_ranges(self):
        """Trust labels follow score thresholds."""
        from bahamut.intelligence.agent_performance import get_strategy_trust
        # High win rate + high PF → high trust
        with patch("bahamut.db.query.run_query_one", return_value={"total": 20, "wins": 16, "losses": 4, "avg_pnl": 50, "gross_profit": 1000, "gross_loss": 200}):
            recent = [{"pnl": 50}] * 10
            with patch("bahamut.db.query.run_query", return_value=recent):
                trust = get_strategy_trust("v5_tuned")
        assert trust["trust_label"] == "high"


# ═══════════════════════════════════════════
# 3. AGENT LEADERBOARD FROM REAL DATA
# ═══════════════════════════════════════════

class TestAgentLeaderboard:
    def test_leaderboard_provisional_when_no_data(self):
        """With no trades, all entries are provisional."""
        from bahamut.intelligence.agent_performance import get_agent_leaderboard
        with patch("bahamut.db.query.run_query_one", return_value={"total": 0}):
            with patch("bahamut.db.query.run_query", return_value=[]):
                lb = get_agent_leaderboard()
        assert len(lb) == 3  # v5_base, v5_tuned, v9_breakout
        for entry in lb:
            assert entry["provisional"] is True
            assert entry["tier"] == "—"

    def test_leaderboard_ranks_by_score(self):
        """Strategies ranked by composite score when data exists."""
        from bahamut.intelligence.agent_performance import get_agent_leaderboard

        def mock_query_one(sql, params=None):
            s = params.get("s", "") if params else ""
            if s == "v5_base":
                return {"total": 20, "wins": 14, "losses": 6, "avg_pnl": 30, "gross_profit": 600, "gross_loss": 180}
            elif s == "v5_tuned":
                return {"total": 15, "wins": 8, "losses": 7, "avg_pnl": 5, "gross_profit": 200, "gross_loss": 175}
            return {"total": 12, "wins": 7, "losses": 5, "avg_pnl": 15, "gross_profit": 180, "gross_loss": 75}

        with patch("bahamut.db.query.run_query_one", side_effect=mock_query_one):
            with patch("bahamut.db.query.run_query", return_value=[{"pnl": 10}] * 10):
                lb = get_agent_leaderboard()

        assert lb[0]["rank"] == 1
        assert lb[0]["composite_score"] >= lb[1]["composite_score"]
        assert not lb[0]["provisional"]  # 20 trades > MIN_SAMPLES
        assert lb[0]["data_source"] == "training_trades"

    def test_leaderboard_backward_compat(self):
        """Leaderboard entries have agent_id field (backward compat)."""
        from bahamut.intelligence.agent_performance import get_agent_leaderboard
        with patch("bahamut.db.query.run_query_one", return_value={"total": 0}):
            with patch("bahamut.db.query.run_query", return_value=[]):
                lb = get_agent_leaderboard()
        for entry in lb:
            assert "agent_id" in entry  # backward compat
            assert "composite_score" in entry
            assert "rank" in entry


# ═══════════════════════════════════════════
# 4. ADAPTIVE RISK
# ═══════════════════════════════════════════

class TestAdaptiveRisk:
    def test_inactive_below_threshold(self):
        """Adaptive risk inactive when not enough trades."""
        from bahamut.intelligence.adaptive_risk import compute_adaptive_adjustments
        with patch("bahamut.db.query.run_query_one", return_value={"cnt": 5}):
            with patch("bahamut.db.query.run_query", return_value=[]):
                result = compute_adaptive_adjustments()
        assert result["active"] is False
        assert "Insufficient" in result["reason"]
        # Should return base values, not adjusted
        for k, v in result["adjustments"].items():
            assert v["delta"] == 0

    def test_active_above_threshold(self):
        """Adaptive risk active with enough trades."""
        from bahamut.intelligence.adaptive_risk import compute_adaptive_adjustments, MIN_TRADES_FOR_ADAPTIVE

        def mock_one(sql, params=None):
            if "COUNT" in sql:
                return {"cnt": 30}
            if "SUM(pnl)" in sql:
                return {"total_pnl": 500}
            return {}

        with patch("bahamut.db.query.run_query_one", side_effect=mock_one):
            recent = [{"pnl": 20 + i} for i in range(10)]
            with patch("bahamut.db.query.run_query", return_value=recent):
                result = compute_adaptive_adjustments()
        assert result["active"] is True
        assert result["conditions"]["trades_available"] == 30

    def test_losing_streak_tightens(self):
        """Losing streak → tighter risk thresholds."""
        from bahamut.intelligence.adaptive_risk import _calculate_adjustments
        conditions = {
            "volatility_level": "normal",
            "drawdown_trend": "worsening",
            "streak": -4,
            "recent_win_rate": 0.3,
        }
        adj = _calculate_adjustments(conditions)
        # Losing streak should tighten tail risk
        assert adj["tail_risk_threshold"]["delta"] < 0


# ═══════════════════════════════════════════
# 5. NO PRODUCTION CONTAMINATION
# ═══════════════════════════════════════════

class TestNoContamination:
    def test_learning_reads_training_trades_not_paper_positions(self):
        """Learning progress queries training_trades, not old paper_positions."""
        import inspect
        from bahamut.intelligence.learning_progress import get_learning_progress
        source = inspect.getsource(get_learning_progress)
        assert "training_trades" in source
        assert "paper_positions" not in source

    def test_adaptive_reads_training_trades(self):
        """Adaptive risk reads from training_trades, not paper_positions."""
        import inspect
        from bahamut.intelligence.adaptive_risk import _assess_conditions
        source = inspect.getsource(_assess_conditions)
        assert "training_trades" in source
        assert "paper_positions" not in source

    def test_leaderboard_reads_training_trades(self):
        """Leaderboard reads from training_trades, not agent_trade_performance."""
        import inspect
        from bahamut.intelligence.agent_performance import _get_strategy_stats
        source = inspect.getsource(_get_strategy_stats)
        assert "training_trades" in source
        assert "agent_trade_performance" not in source


# ═══════════════════════════════════════════
# 6. FEED_LEARNING UPDATES ALL SYSTEMS
# ═══════════════════════════════════════════

class TestFeedLearning:
    def test_feed_updates_strategy_stats(self):
        """_feed_learning writes to strategy stats Redis key."""
        from bahamut.training.engine import _feed_learning, TrainingTrade
        import json

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        trade = TrainingTrade(
            trade_id="t1", position_id="p1", asset="BTCUSD", asset_class="crypto",
            strategy="v5_base", direction="LONG", entry_price=68000, exit_price=69000,
            stop_price=66000, tp_price=72000, size=0.01, risk_amount=200,
            pnl=10, pnl_pct=0.05, entry_time="t0", exit_time="t1",
            exit_reason="TP", bars_held=5,
        )

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            _feed_learning(trade)

        # Verify Redis set was called for strategy stats
        calls = [str(c) for c in mock_redis.set.call_args_list]
        assert any("strategy_stats:v5_base" in c for c in calls)
        assert any("class_stats:crypto" in c for c in calls)
        assert any("trust:v5_base" in c for c in calls)
        mock_redis.incr.assert_called_once_with("bahamut:training:total_closed_trades")

    def test_feed_updates_trust_score(self):
        """_feed_learning updates trust score in Redis."""
        from bahamut.training.engine import _feed_learning, TrainingTrade
        import json

        stored_trust = {"trades": 9, "wins": 6, "recent_pnls": [10, -5, 20, 15, -10, 30, -5, 20, 15],
                        "trust_score": 0.5, "provisional": True}
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda k: json.dumps(stored_trust) if "trust:" in k else None

        trade = TrainingTrade(
            trade_id="t2", position_id="p2", asset="ETHUSD", asset_class="crypto",
            strategy="v5_base", direction="LONG", entry_price=2000, exit_price=2100,
            stop_price=1900, tp_price=2200, size=0.1, risk_amount=100,
            pnl=10, pnl_pct=0.1, entry_time="t0", exit_time="t1",
            exit_reason="TP", bars_held=3,
        )

        with patch("bahamut.training.engine._get_redis", return_value=mock_redis):
            _feed_learning(trade)

        # The 10th trade should flip provisional → False
        trust_calls = [c for c in mock_redis.set.call_args_list if "trust:v5_base" in str(c)]
        assert len(trust_calls) >= 1
        saved = json.loads(trust_calls[0][0][1])
        assert saved["trades"] == 10
        assert saved["provisional"] is False  # Crossed MIN_SAMPLES_FOR_TRUST threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
