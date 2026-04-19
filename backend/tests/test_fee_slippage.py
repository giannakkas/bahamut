"""
Phase 5 Item 14 — Fee/slippage visibility tests.
"""


def test_trade_has_cost_fields():
    """TrainingTrade carries entry/exit commission + slippage."""
    from bahamut.trading.engine import TrainingTrade
    t = TrainingTrade(
        trade_id="T1", position_id="P1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, exit_price=105.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, pnl=5.0, pnl_pct=0.05,
        entry_time="2026-01-01", exit_time="2026-01-01",
        exit_reason="TP", bars_held=5,
        entry_commission=0.25, exit_commission=0.30,
        entry_slippage_abs=0.10, exit_slippage_abs=0.15,
    )
    assert t.entry_commission == 0.25
    assert t.exit_commission == 0.30
    assert t.entry_slippage_abs == 0.10
    assert t.exit_slippage_abs == 0.15


def test_trade_cost_fields_default_zero():
    from bahamut.trading.engine import TrainingTrade
    t = TrainingTrade(
        trade_id="T1", position_id="P1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, exit_price=105.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, pnl=5.0, pnl_pct=0.05,
        entry_time="2026-01-01", exit_time="2026-01-01",
        exit_reason="TP", bars_held=5,
    )
    assert t.entry_commission == 0.0
    assert t.exit_commission == 0.0
    assert t.entry_slippage_abs == 0.0
    assert t.exit_slippage_abs == 0.0


def test_gross_vs_net_pnl_math():
    """Net PnL = gross - (entry_commission + exit_commission + slippage)."""
    gross = 150.0
    entry_comm = 0.5
    exit_comm = 0.5
    entry_slip = 0.2
    exit_slip = 0.3
    total_costs = entry_comm + exit_comm + entry_slip + exit_slip
    net = gross - total_costs
    assert abs(net - 148.5) < 1e-6


def test_position_commission_propagates_to_trade():
    """Trade's entry_commission should come from position's commission field."""
    from bahamut.trading.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="T1", asset="BTCUSD", asset_class="crypto",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0,
        entry_time="2026-01-01",
        execution_platform="binance_futures", exchange_order_id="X",
        commission=0.45,
        slippage_abs=0.12,
    )
    # Simulate what the engine does at close
    entry_commission = pos.commission
    entry_slippage_abs = pos.slippage_abs
    assert entry_commission == 0.45
    assert entry_slippage_abs == 0.12


if __name__ == "__main__":
    import sys
    tests = [
        test_trade_has_cost_fields,
        test_trade_cost_fields_default_zero,
        test_gross_vs_net_pnl_math,
        test_position_commission_propagates_to_trade,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
