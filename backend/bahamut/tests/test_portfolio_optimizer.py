"""
Bahamut.AI — Portfolio Optimizer Tests

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_portfolio_optimizer.py -v
"""
import pytest
from bahamut.training.portfolio_optimizer import (
    evaluate_candidate, _build_portfolio_snapshot,
    get_portfolio_constraints_summary, CORRELATION_CLUSTERS,
)


def _snap(positions: list[dict]) -> dict:
    return _build_portfolio_snapshot(positions)


class TestCorrelationClusters:
    def test_btc_eth_in_same_cluster(self):
        assert any(
            "BTCUSD" in c["assets"] and "ETHUSD" in c["assets"]
            for c in CORRELATION_CLUSTERS.values()
        )

    def test_spy_qqq_in_same_cluster(self):
        assert any(
            "SPY" in c["assets"] and "QQQ" in c["assets"]
            for c in CORRELATION_CLUSTERS.values()
        )

    def test_cluster_blocks_third_member(self):
        """Two BTC+ETH positions → cluster full, BTCUSD blocked."""
        snap = _snap([
            {"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
            {"asset": "ETHUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
        ])
        result = evaluate_candidate("BTCUSD", "crypto", "v9_breakout", "LONG", snap)
        assert result["decision"] == "BLOCK"
        assert any("cluster" in r.lower() or "already" in r.lower() for r in result["reasons"])

    def test_cluster_penalizes_overlap(self):
        """One BTC position → ETH is penalized but allowed."""
        snap = _snap([
            {"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
        ])
        result = evaluate_candidate("ETHUSD", "crypto", "v5_base", "LONG", snap)
        assert result["penalty"] > 0
        assert result["decision"] == "PENALIZE"
        assert any("overlap" in r.lower() for r in result["reasons"])

    def test_unrelated_asset_no_penalty(self):
        """BTC position → EURUSD has zero cluster overlap."""
        snap = _snap([
            {"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
        ])
        result = evaluate_candidate("EURUSD", "forex", "v5_base", "LONG", snap)
        assert result["decision"] == "ALLOW"
        assert result["penalty"] == 0


class TestDirectionLimits:
    def test_direction_block(self):
        """8 longs → next long is blocked."""
        positions = [
            {"asset": f"A{i}", "asset_class": f"c{i}", "strategy": "v5_base", "direction": "LONG"}
            for i in range(8)
        ]
        snap = _snap(positions)
        result = evaluate_candidate("NEW", "forex", "v5_base", "LONG", snap)
        assert result["decision"] == "BLOCK"
        assert any("direction" in r.lower() for r in result["reasons"])

    def test_opposite_direction_allowed(self):
        """8 longs → short is still allowed."""
        positions = [
            {"asset": f"A{i}", "asset_class": f"c{i}", "strategy": "v5_base", "direction": "LONG"}
            for i in range(8)
        ]
        snap = _snap(positions)
        result = evaluate_candidate("NEW", "forex", "v5_base", "SHORT", snap)
        assert result["decision"] != "BLOCK" or not any("direction" in r.lower() for r in result["reasons"])


class TestClassLimits:
    def test_class_full_blocks(self):
        """5 crypto positions → next crypto blocked."""
        positions = [
            {"asset": f"CRYPTO{i}", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"}
            for i in range(5)
        ]
        snap = _snap(positions)
        result = evaluate_candidate("NEWCRYPTO", "crypto", "v5_base", "LONG", snap)
        assert result["decision"] == "BLOCK"
        assert any("class full" in r.lower() for r in result["reasons"])

    def test_different_class_allowed(self):
        """5 crypto positions → forex still allowed."""
        positions = [
            {"asset": f"CRYPTO{i}", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"}
            for i in range(5)
        ]
        snap = _snap(positions)
        result = evaluate_candidate("EURUSD", "forex", "v5_base", "LONG", snap)
        # Not blocked by class (forex is empty)
        assert not any("class full" in r.lower() for r in result["reasons"])


class TestSameDirectionSameClass:
    def test_concentrated_blocks(self):
        """3 crypto longs → 4th crypto long blocked."""
        positions = [
            {"asset": f"C{i}", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"}
            for i in range(3)
        ]
        snap = _snap(positions)
        result = evaluate_candidate("NEWC", "crypto", "v5_base", "LONG", snap)
        assert result["decision"] == "BLOCK"
        assert any("concentrated" in r.lower() for r in result["reasons"])


class TestPortfolioSnapshot:
    def test_snapshot_counts(self):
        snap = _snap([
            {"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
            {"asset": "EURUSD", "asset_class": "forex", "strategy": "v9_breakout", "direction": "SHORT"},
        ])
        assert snap["total"] == 2
        assert snap["longs"] == 1
        assert snap["shorts"] == 1
        assert snap["by_class"]["crypto"] == 1
        assert snap["by_class"]["forex"] == 1

    def test_constraints_summary(self):
        positions = [
            {"asset": "BTCUSD", "asset_class": "crypto", "strategy": "v5_base", "direction": "LONG"},
        ]
        summary = get_portfolio_constraints_summary(positions)
        assert summary["total_positions"] == 1
        assert summary["longs"] == 1
        assert "crypto" in summary["by_class"]
        assert "limits" in summary


class TestIsolation:
    def test_no_production_imports(self):
        import inspect
        from bahamut.training import portfolio_optimizer
        source = inspect.getsource(portfolio_optimizer)
        assert "ExecutionEngine" not in source
        assert "get_execution_engine" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
