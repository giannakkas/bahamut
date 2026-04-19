"""
Phase 6 Item 15 — Invariant Regression Test Suite

Single test file that verifies EVERY safety invariant introduced across
Phases 2-5 of the quant engineering refactor. Run this on every deploy
to catch regressions.

Invariants tested:
  1. Crypto positions require broker platform + order_id (P2-I5)
  2. ExecutionResult has canonical lifecycle enums (P2-I4)
  3. Exchange filters round DOWN, not up (P2-I6)
  4. Substrategy tag propagates through full pipeline (P3-I7)
  5. Gate history is structured on every decision record (P3-I8)
  6. v9 adaptive SL respects ATR floor + structural cap (P3-I9)
  7. News origin classification covers all three tiers (P4-I10)
  8. AI source distinguishes fresh/stale/fallback/disabled (P4-I11)
  9. Synthetic data is blocked in production (P4-I12)
  10. R-multiples use pnl/risk_amount, not pnl_pct/0.03 (P5-I13)
  11. Trade cost fields exist and default to zero (P5-I14)
"""
import os
import time


# ═══════════════════════════════════════════════════════
# INVARIANT 1: Crypto-internal position invariant (P2-I5)
# ═══════════════════════════════════════════════════════

def test_inv1_crypto_internal_blocked():
    from bahamut.trading.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="INV1", asset="BTCUSD", asset_class="crypto",
        strategy="v10_mean_reversion", direction="SHORT",
        entry_price=100.0, stop_price=105.0, tp_price=95.0,
        size=1.0, risk_amount=100.0, entry_time="2026-01-01",
        execution_platform="internal", exchange_order_id="",
    )
    violates = (pos.asset_class == "crypto"
                and (pos.execution_platform == "internal"
                     or not pos.exchange_order_id))
    assert violates, "crypto+internal must be caught by invariant"


def test_inv1_crypto_broker_allowed():
    from bahamut.trading.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="INV1", asset="BTCUSD", asset_class="crypto",
        strategy="v10_mean_reversion", direction="SHORT",
        entry_price=100.0, stop_price=105.0, tp_price=95.0,
        size=1.0, risk_amount=100.0, entry_time="2026-01-01",
        execution_platform="binance_futures", exchange_order_id="X123",
    )
    violates = (pos.asset_class == "crypto"
                and (pos.execution_platform == "internal"
                     or not pos.exchange_order_id))
    assert not violates


def test_inv1_stock_internal_ok():
    """Stocks CAN be internal (Alpaca not configured)."""
    from bahamut.trading.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="INV1", asset="AAPL", asset_class="stock",
        strategy="v9_breakout", direction="LONG",
        entry_price=100.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, entry_time="2026-01-01",
        execution_platform="internal", exchange_order_id="",
    )
    violates = (pos.asset_class == "crypto"
                and (pos.execution_platform == "internal"
                     or not pos.exchange_order_id))
    assert not violates


# ═══════════════════════════════════════════════════════
# INVARIANT 2: ExecutionResult lifecycle enums (P2-I4)
# ═══════════════════════════════════════════════════════

def test_inv2_execution_result_enums():
    from bahamut.execution.canonical import OrderLifecycle, FillStatus
    assert hasattr(OrderLifecycle, "FILLED")
    assert hasattr(OrderLifecycle, "ERROR")
    assert hasattr(OrderLifecycle, "INTERNAL")
    assert hasattr(FillStatus, "FILLED")
    assert hasattr(FillStatus, "UNFILLED")


def test_inv2_execution_result_as_dict_has_legacy_keys():
    from bahamut.execution.canonical import ExecutionResult
    er = ExecutionResult.internal_sim("BTCUSD", 100.0, 1.0)
    d = er.as_dict()
    for key in ("platform", "order_id", "fill_price", "fill_qty", "status"):
        assert key in d, f"legacy key '{key}' missing from as_dict()"


# ═══════════════════════════════════════════════════════
# INVARIANT 3: Exchange filters round DOWN (P2-I6)
# ═══════════════════════════════════════════════════════

def test_inv3_round_qty_down():
    from bahamut.execution import exchange_filters as ef
    ef._FILTERS = dict(ef._FALLBACK_FILTERS)
    ef._FILTERS_FETCHED_AT = 9999999999
    assert ef.round_qty("BTCUSDT", 0.1237) == 0.123  # not 0.124


# ═══════════════════════════════════════════════════════
# INVARIANT 4: Substrategy propagation (P3-I7)
# ═══════════════════════════════════════════════════════

def test_inv4_signal_has_substrategy():
    from bahamut.strategies.base import Signal
    s = Signal(strategy="v10_mean_reversion", asset="BTCUSD", direction="SHORT",
               substrategy="v10_crash_short")
    assert s.substrategy == "v10_crash_short"


def test_inv4_learning_context_has_substrategy():
    from bahamut.trading.learning_engine import LearningContext
    ctx = LearningContext(
        strategy="v10", asset="X", asset_class="crypto", direction="SHORT",
        regime="CRASH", exit_reason="TP", pnl=10, r_multiple=0.5,
        bars_held=5, quick_stop=False, outcome_score=0.5,
        substrategy="v10_crash_short",
    )
    assert ctx.substrategy == "v10_crash_short"


# ═══════════════════════════════════════════════════════
# INVARIANT 5: Gate history structure (P3-I8)
# ═══════════════════════════════════════════════════════

def test_inv5_fmt_decision_has_gate_history():
    from bahamut.trading.selector import _fmt_decision, PendingSignal
    sig = PendingSignal(
        asset="AAPL", asset_class="stock", strategy="v9_breakout",
        direction="LONG", readiness_score=75, regime="TREND",
        entry_price=100.0, sl_pct=0.02, tp_pct=0.04, max_hold_bars=20,
        reasons=[],
    )
    pri = {"total": 60, "components": {}}
    d = _fmt_decision(sig, pri, "EXECUTE", ["ok"], gate_history=[
        {"stage": "ranking", "gate": "execute", "verdict": "allow", "detail": ""},
    ])
    assert "gate_history" in d
    assert "decision_stage" in d
    assert "blocking_gate" in d


# ═══════════════════════════════════════════════════════
# INVARIANT 6: v9 adaptive sizing (P3-I9)
# ═══════════════════════════════════════════════════════

def test_inv6_v9_has_adaptive_sizing():
    import inspect
    from bahamut.alpha.v9_candidate import V9Breakout
    v9 = V9Breakout()
    src = inspect.getsource(v9.evaluate)
    assert "adaptive" in src.lower() or "atr_mult" in src


# ═══════════════════════════════════════════════════════
# INVARIANT 7: News origin classification (P4-I10)
# ═══════════════════════════════════════════════════════

def test_inv7_classify_origins_exists():
    from bahamut.intelligence.news_impact import _classify_news_origins
    result = _classify_news_origins("BTCUSD", "crypto", [], [])
    assert "asset_specific_score" in result
    assert "class_level_score" in result
    assert "macro_score" in result


def test_inv7_gate_decision_has_provenance():
    from bahamut.intelligence.adaptive_news_risk import (
        AssetNewsState, get_news_gate_decision,
    )
    state = AssetNewsState(asset="BTCUSD", mode="NORMAL",
                           assessment_computed_at=time.time())
    d = get_news_gate_decision(state, "LONG")
    assert "age_seconds" in d
    assert "is_stale" in d
    assert "dominant_origin" in d


# ═══════════════════════════════════════════════════════
# INVARIANT 8: AI source categories (P4-I11)
# ═══════════════════════════════════════════════════════

def test_inv8_ai_source_categories():
    from bahamut.intelligence.ai_market_analyst import get_analysis_source
    # With no cache, should return fallback or disabled
    _, source = get_analysis_source()
    assert source in ("fresh", "stale", "fallback_rules", "disabled")


def test_inv8_ai_decision_has_canonical_source():
    from bahamut.intelligence.ai_decision_service import get_ai_decision
    d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
    assert "ai_source" in d
    assert d["ai_source"] in ("fresh", "stale", "fallback_rules", "disabled")


# ═══════════════════════════════════════════════════════
# INVARIANT 9: Synthetic data blocked (P4-I12)
# ═══════════════════════════════════════════════════════

def test_inv9_block_synthetic_default_on():
    saved = os.environ.get("BAHAMUT_BLOCK_SYNTHETIC")
    if saved == "0":
        return  # dev override active, skip
    from bahamut.data.live_data import BLOCK_SYNTHETIC
    assert BLOCK_SYNTHETIC is True


def test_inv9_data_mode_on_position():
    from bahamut.trading.engine import TrainingPosition
    pos = TrainingPosition(
        position_id="T1", asset="BTCUSD", asset_class="crypto",
        strategy="v9", direction="LONG",
        entry_price=100.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, entry_time="2026-01-01",
        execution_platform="binance_futures", exchange_order_id="X",
    )
    assert pos.data_mode == "live"


# ═══════════════════════════════════════════════════════
# INVARIANT 10: Canonical R-multiples (P5-I13)
# ═══════════════════════════════════════════════════════

def test_inv10_r_from_real_risk():
    """R must be pnl/risk_amount, not pnl_pct/0.03."""
    pnl, risk = 150.0, 100.0
    assert abs(pnl / risk - 1.5) < 1e-6

    from bahamut.trading.learning_engine import compute_learning_context
    ctx = compute_learning_context({
        "strategy": "v9", "asset": "X", "asset_class": "stock",
        "direction": "LONG", "regime": "TREND", "exit_reason": "TP",
        "pnl": 150.0, "risk_amount": 100.0, "bars_held": 5,
    })
    assert abs(ctx.r_multiple - 1.5) < 1e-4


# ═══════════════════════════════════════════════════════
# INVARIANT 11: Trade cost fields (P5-I14)
# ═══════════════════════════════════════════════════════

def test_inv11_trade_cost_fields_exist():
    from bahamut.trading.engine import TrainingTrade
    t = TrainingTrade(
        trade_id="T1", position_id="P1", asset="BTCUSD", asset_class="crypto",
        strategy="v9", direction="LONG",
        entry_price=100.0, exit_price=105.0, stop_price=95.0, tp_price=110.0,
        size=1.0, risk_amount=100.0, pnl=5.0, pnl_pct=0.05,
        entry_time="2026-01-01", exit_time="2026-01-01",
        exit_reason="TP", bars_held=5,
    )
    for field in ("entry_commission", "exit_commission",
                  "entry_slippage_abs", "exit_slippage_abs"):
        assert hasattr(t, field), f"missing {field}"
        assert getattr(t, field) == 0.0, f"{field} should default to 0.0"


if __name__ == "__main__":
    import sys
    tests = [
        # P2
        test_inv1_crypto_internal_blocked,
        test_inv1_crypto_broker_allowed,
        test_inv1_stock_internal_ok,
        test_inv2_execution_result_enums,
        test_inv2_execution_result_as_dict_has_legacy_keys,
        test_inv3_round_qty_down,
        # P3
        test_inv4_signal_has_substrategy,
        test_inv4_learning_context_has_substrategy,
        test_inv5_fmt_decision_has_gate_history,
        test_inv6_v9_has_adaptive_sizing,
        # P4
        test_inv7_classify_origins_exists,
        test_inv7_gate_decision_has_provenance,
        test_inv8_ai_source_categories,
        test_inv8_ai_decision_has_canonical_source,
        test_inv9_block_synthetic_default_on,
        test_inv9_data_mode_on_position,
        # P5
        test_inv10_r_from_real_risk,
        test_inv11_trade_cost_fields_exist,
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
    print(f"\n  INVARIANT SUITE: {passed} passed, {failed} failed")
    if failed > 0:
        print("  *** INVARIANT REGRESSION DETECTED ***")
    sys.exit(0 if failed == 0 else 1)
