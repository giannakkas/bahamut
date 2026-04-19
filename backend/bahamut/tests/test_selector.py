"""
Bahamut.AI — Selector Engine Tests

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_selector.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from bahamut.trading.selector import PendingSignal, select_candidates, _compute_priority


def _sig(asset="BTCUSD", cls="crypto", strat="v5_base", score=85,
         regime="TREND", direction="LONG") -> PendingSignal:
    return PendingSignal(
        asset=asset, asset_class=cls, strategy=strat, direction=direction,
        readiness_score=score, regime=regime, entry_price=68000,
        sl_pct=0.08, tp_pct=0.16, max_hold_bars=30, reasons=["test"],
    )


class TestCompositeScoring:
    def test_high_readiness_high_priority(self):
        sig = _sig(score=95)
        pri = _compute_priority(sig, [], {})
        assert pri["total"] > 50
        assert pri["components"]["readiness"] == 38  # 95 * 0.4

    def test_reward_risk_contributes(self):
        sig = _sig()  # tp=0.16, sl=0.08 → R:R = 2.0
        pri = _compute_priority(sig, [], {})
        assert pri["components"]["reward_risk"] == 10  # 2.0 * 5

    def test_portfolio_overlap_penalized(self):
        sig = _sig(asset="ETHUSD", cls="crypto")
        existing = [{"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base"}]
        pri = _compute_priority(sig, existing, {})
        assert pri["components"]["portfolio_fit"] < 15  # penalized

    def test_same_asset_heavily_penalized(self):
        sig = _sig(asset="BTCUSD")
        existing = [{"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base"}]
        pri = _compute_priority(sig, existing, {})
        assert pri["components"]["portfolio_fit"] == 0

    def test_strategy_track_provisional(self):
        sig = _sig()
        pri = _compute_priority(sig, [], {"v5_base": {"trades": 5, "win_rate": 0.6}})
        assert pri["components"]["strategy_track"] == 5  # provisional


class TestSelection:
    @pytest.fixture(autouse=True)
    def _mock_positions(self):
        with patch("bahamut.trading.engine._load_positions", return_value=[]):
            with patch("bahamut.trading.selector._load_strategy_stats", return_value={}):
                yield

    def test_below_threshold_rejected(self):
        result = select_candidates([_sig(score=50)])
        assert len(result["execute"]) == 0
        assert len(result["rejected"]) == 1
        assert "threshold" in result["rejected"][0]["reasons"][0].lower()

    def test_above_threshold_selected(self):
        result = select_candidates([_sig(score=90, regime="TREND")])
        assert len(result["execute"]) == 1
        assert result["execute"][0]["decision"] == "EXECUTE"

    def test_wrong_regime_watchlisted(self):
        result = select_candidates([_sig(score=90, regime="RANGE")])
        assert len(result["execute"]) == 0
        assert len(result["watchlist"]) == 1
        assert "regime" in result["watchlist"][0]["reasons"][0].lower()

    def test_max_per_cycle_cap(self):
        sigs = [_sig(asset=f"ASSET{i}", cls=f"class{i}", score=90, regime="TREND") for i in range(5)]
        result = select_candidates(sigs)
        assert len(result["execute"]) == 3  # default max
        assert len(result["watchlist"]) == 2
        assert "cycle cap" in result["watchlist"][0]["reasons"][0].lower()

    def test_max_per_class_cap(self):
        sigs = [
            _sig(asset="A1", cls="crypto", strat="v5_base", score=90, regime="TREND"),
            _sig(asset="A2", cls="crypto", strat="v9_breakout", score=88, regime="BREAKOUT"),
            _sig(asset="A3", cls="crypto", strat="v5_tuned", score=85, regime="TREND"),
        ]
        result = select_candidates(sigs)
        # max_per_class = 2 default
        assert len([e for e in result["execute"] if e["asset_class"] == "crypto"]) <= 2

    def test_no_duplicate_asset(self):
        sigs = [
            _sig(asset="BTC", cls="crypto", strat="v5_base", score=90, regime="TREND"),
            _sig(asset="BTC", cls="crypto", strat="v9_breakout", score=88, regime="BREAKOUT"),
        ]
        result = select_candidates(sigs)
        executed_assets = [e["asset"] for e in result["execute"]]
        assert len(set(executed_assets)) == len(executed_assets)

    def test_summary_counts(self):
        sigs = [
            _sig(asset="A", cls="c1", score=90, regime="TREND"),
            _sig(asset="B", cls="c2", score=50),
            _sig(asset="C", cls="c3", score=85, regime="RANGE"),
        ]
        result = select_candidates(sigs)
        s = result["summary"]
        assert s["total_signals"] == 3
        assert s["selected"] + s["watchlisted"] + s["rejected"] == 3


class TestIsolation:
    def test_selector_does_not_import_production(self):
        import inspect
        from bahamut.trading import selector
        source = inspect.getsource(selector)
        assert "get_execution_engine" not in source
        assert "ExecutionEngine" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
