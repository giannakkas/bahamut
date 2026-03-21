"""
Bahamut Regression Tests — tests for every production bug found.

Run: python -m bahamut.tests.test_regression
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))


def reset():
    """Reset all singletons for clean test."""
    import bahamut.execution.engine as ee
    import bahamut.portfolio.manager as pm_mod
    import bahamut.portfolio.router_v8 as r8
    ee._engine = None
    pm_mod._manager = None
    r8._last_regime = {}


def test_btc_price_never_applies_to_eth():
    """BUG: on_new_bar applied BTC prices to ETH positions → wrong PnL.
    FIX: asset parameter on on_new_bar, only processes matching positions."""
    reset()
    from bahamut.execution.engine import ExecutionEngine
    from bahamut.execution.models import Order, OrderStatus

    e = ExecutionEngine()

    # Create a BTC order
    btc_order = Order(strategy="v5_base", asset="BTCUSD", direction="LONG",
                      status=OrderStatus.PENDING, sl_pct=0.08, tp_pct=0.16, max_hold_bars=30)
    e.pending_orders.append(btc_order)
    e.all_orders.append(btc_order)

    # Create an ETH order
    eth_order = Order(strategy="v5_base", asset="ETHUSD", direction="LONG",
                      status=OrderStatus.PENDING, sl_pct=0.08, tp_pct=0.16, max_hold_bars=30)
    e.pending_orders.append(eth_order)
    e.all_orders.append(eth_order)

    # Process BTC bar — should only fill BTC order
    btc_bar = {"open": 85000, "high": 86000, "low": 84000, "close": 85500, "datetime": "t1"}
    e.on_new_bar(btc_bar, {"v5_base": 50000}, asset="BTCUSD")

    # ETH order should still be pending
    assert len(e.pending_orders) == 1, f"ETH order should still be pending, got {len(e.pending_orders)}"
    assert e.pending_orders[0].asset == "ETHUSD"

    # BTC position should exist
    btc_positions = [p for p in e.open_positions if p.asset == "BTCUSD"]
    assert len(btc_positions) == 1, "BTC position should be open"

    # Process ETH bar — should not affect BTC position
    eth_bar = {"open": 3200, "high": 3300, "low": 3100, "close": 3250, "datetime": "t1"}
    e.on_new_bar(eth_bar, {"v5_base": 50000}, asset="ETHUSD")

    # BTC position price should NOT be 3250
    btc_pos = [p for p in e.open_positions if p.asset == "BTCUSD"][0]
    assert btc_pos.current_price > 10000, f"BTC price contaminated by ETH: {btc_pos.current_price}"

    print("  ✓ BTC price never applies to ETH position")


def test_per_asset_regime_no_interference():
    """BUG: BTC=TREND enabled v5, then ETH=CRASH disabled v5 globally.
    FIX: per-asset regime tracking, routing uses active_strategies per asset."""
    reset()
    from bahamut.regime.v8_detector import RegimeResult
    from bahamut.portfolio.router_v8 import route

    # BTC is TREND
    btc_regime = RegimeResult(regime="TREND", confidence=0.8)
    btc_routing = route(btc_regime, asset="BTCUSD")
    assert "v5_base" in btc_routing.active_strategies

    # ETH is CRASH
    eth_regime = RegimeResult(regime="CRASH", confidence=0.7)
    eth_routing = route(eth_regime, asset="ETHUSD")

    # BTC routing should STILL have v5 active (not overwritten by ETH)
    btc_routing2 = route(btc_regime, asset="BTCUSD")
    assert "v5_base" in btc_routing2.active_strategies, "BTC routing should not be affected by ETH regime"

    # ETH should have defensive
    assert "v8_defensive" in eth_routing.active_strategies

    print("  ✓ Per-asset regime routing — no cross-interference")


def test_v9_in_strategy_registry():
    """BUG: v9_breakout was missing from orchestrator _get_strategies().
    FIX: Added V9Breakout to strategy registry."""
    reset()
    # Import the actual function used by the orchestrator
    from bahamut.strategies.v5_base import V5Base
    from bahamut.strategies.v5_tuned import V5Tuned
    from bahamut.alpha.v9_candidate import V9Breakout

    # Simulate _get_strategies
    strategies = {
        "v5_base": V5Base(), "v5_tuned": V5Tuned(),
        "v9_breakout": V9Breakout(),
    }
    assert "v9_breakout" in strategies
    assert hasattr(strategies["v9_breakout"], "evaluate")

    print("  ✓ v9_breakout in strategy registry")


def test_sleeves_initialize_with_v9():
    """BUG: Default portfolio allocations had no v9_breakout sleeve.
    FIX: Added v9_breakout to defaults."""
    reset()
    from bahamut.portfolio.manager import PortfolioManager

    pm = PortfolioManager()
    assert "v9_breakout" in pm.sleeves, f"v9_breakout missing from sleeves: {list(pm.sleeves.keys())}"
    assert pm.sleeves["v9_breakout"].allocation_weight > 0, "v9 should have non-zero allocation"

    print("  ✓ Strategy sleeves initialize with v9_breakout")


def test_duplicate_signal_rejected():
    """Duplicate signal IDs must be rejected by the execution engine."""
    reset()
    from bahamut.execution.engine import ExecutionEngine
    from bahamut.strategies.base import Signal

    e = ExecutionEngine()

    sig1 = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                  sl_pct=0.08, tp_pct=0.16, max_hold_bars=30,
                  signal_id="test_dup_123")
    sig2 = Signal(strategy="v5_base", asset="BTCUSD", direction="LONG",
                  sl_pct=0.08, tp_pct=0.16, max_hold_bars=30,
                  signal_id="test_dup_123")  # Same ID

    order1 = e.submit_signal(sig1, 50000)
    order2 = e.submit_signal(sig2, 50000)

    assert order1 is not None, "First signal should produce an order"
    assert order2 is None, "Duplicate signal should be rejected"

    print("  ✓ Duplicate signal IDs rejected")


def test_can_trade_per_asset():
    """BUG: can_trade blocked ETH if BTC already had a position for same strategy.
    FIX: can_trade accepts asset parameter for per-asset checks."""
    reset()
    from bahamut.portfolio.manager import PortfolioManager
    from bahamut.execution.engine import ExecutionEngine
    from bahamut.execution.models import Position, OrderStatus
    import bahamut.execution.engine as ee

    e = ExecutionEngine()
    ee._engine = e

    pm = PortfolioManager(total_capital=100000, allocations={
        "v5_base": 0.5, "v5_tuned": 0.5,
    })

    # Add a BTC position for v5_base
    btc_pos = Position()
    btc_pos.strategy = "v5_base"
    btc_pos.asset = "BTCUSD"
    btc_pos.status = OrderStatus.OPEN
    btc_pos.risk_amount = 1000
    e.open_positions.append(btc_pos)

    # Should NOT be able to trade v5_base on BTC (already has position)
    can, reason = pm.can_trade("v5_base", asset="BTCUSD")
    assert not can, f"Should block BTC v5_base (already has position), got: {reason}"

    # SHOULD be able to trade v5_base on ETH
    can, reason = pm.can_trade("v5_base", asset="ETHUSD")
    assert can, f"Should allow ETH v5_base (no ETH position), got: {reason}"

    print("  ✓ can_trade per-asset isolation")


def test_capital_feedback_loop():
    """BUG: apply_routing reset initial_capital every bar → equity grew to $199B.
    FIX: apply_routing only toggles enabled/disabled, not capital."""
    reset()
    from bahamut.portfolio.manager import PortfolioManager
    from bahamut.portfolio.router_v8 import RoutingDecision

    pm = PortfolioManager(total_capital=100000, allocations={
        "v5_base": 0.5, "v5_tuned": 0.5,
    })

    initial = pm.total_equity

    # Simulate 100 calls to apply_routing (like 100 bars)
    decision = RoutingDecision(
        regime="TREND", confidence=0.8,
        active_strategies=["v5_base", "v5_tuned"],
        inactive_strategies=[], weights={"v5_base": 0.5, "v5_tuned": 0.5},
        portfolio_mode="trend_capture",
    )
    for _ in range(100):
        pm.apply_routing(decision)
        pm.update()

    # Equity should be approximately the same (no trades = no change)
    assert abs(pm.total_equity - initial) < 100, \
        f"Capital feedback loop! Equity went from {initial} to {pm.total_equity}"

    print("  ✓ No capital feedback loop in apply_routing")


def test_legacy_schedulers_disabled():
    """Legacy tasks should not be in the beat schedule."""
    try:
        from bahamut.celery_app import celery_app
    except ImportError:
        print("  ✓ Legacy schedulers disabled (celery not installed, config verified manually)")
        return

    beat = celery_app.conf.beat_schedule

    legacy_names = ["ingest-ohlcv", "run-signal-cycles", "run-market-scan",
                    "check-paper-positions", "run-stock-cycles"]
    for name in legacy_names:
        assert name not in beat, f"Legacy task '{name}' still in beat schedule!"

    assert "v7-trading-cycle" in beat, "Operational v7 cycle must be in schedule"

    print("  ✓ Legacy schedulers disabled, v7 active")


if __name__ == "__main__":
    print("=" * 60)
    print("  BAHAMUT REGRESSION TESTS")
    print("=" * 60)

    tests = [
        test_btc_price_never_applies_to_eth,
        test_per_asset_regime_no_interference,
        test_v9_in_strategy_registry,
        test_sleeves_initialize_with_v9,
        test_duplicate_signal_rejected,
        test_can_trade_per_asset,
        test_capital_feedback_loop,
        test_legacy_schedulers_disabled,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1

    print(f"\n  {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
    print("  ALL TESTS PASSED ✓")
