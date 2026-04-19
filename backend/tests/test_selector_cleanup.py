"""
Phase 3 Item 8 — Selector cleanup tests.
Validates the gate_history structure and class_boost labeling.
"""


def _make_sig(**overrides):
    from bahamut.trading.selector import PendingSignal
    defaults = dict(
        asset="AAPL", asset_class="stock", strategy="v9_breakout",
        direction="LONG", readiness_score=75, regime="TREND",
        entry_price=100.0, sl_pct=0.02, tp_pct=0.04, max_hold_bars=20,
        reasons=[],
    )
    defaults.update(overrides)
    return PendingSignal(**defaults)


def test_fmt_decision_includes_gate_history_fields():
    """_fmt_decision emits gate_history / decision_stage / blocking_gate."""
    from bahamut.trading.selector import _fmt_decision
    sig = _make_sig()
    pri = {"total": 60, "components": {"readiness": 40, "trust": 10}}
    d = _fmt_decision(sig, pri, "EXECUTE", ["ok"], gate_history=[
        {"stage": "hard_safety", "gate": "context_gate", "verdict": "allow", "detail": ""},
        {"stage": "ranking", "gate": "execute", "verdict": "allow", "detail": "priority=60"},
    ])
    assert "gate_history" in d
    assert len(d["gate_history"]) == 2
    assert d["decision_stage"] == "ranking"  # last entry's stage for EXECUTE
    assert d["blocking_gate"] == ""  # no block for EXECUTE


def test_fmt_decision_rejected_identifies_blocking_gate():
    from bahamut.trading.selector import _fmt_decision
    sig = _make_sig()
    pri = {"total": 10, "components": {}}
    d = _fmt_decision(sig, pri, "REJECT", ["mature neg"], gate_history=[
        {"stage": "hard_safety", "gate": "context_gate", "verdict": "allow", "detail": ""},
        {"stage": "hard_safety", "gate": "mature_neg_expectancy",
         "verdict": "block", "detail": "expectancy=-0.12, samples=20"},
    ])
    assert d["decision"] == "REJECT"
    assert d["blocking_gate"] == "mature_neg_expectancy"
    assert d["decision_stage"] == "hard_safety"


def test_fmt_decision_legacy_no_gate_history():
    """Calling _fmt_decision without gate_history still works."""
    from bahamut.trading.selector import _fmt_decision
    sig = _make_sig()
    pri = {"total": 60, "components": {}}
    d = _fmt_decision(sig, pri, "EXECUTE", ["ok"])
    assert d["gate_history"] == []
    assert d["blocking_gate"] == ""
    assert d["decision_stage"] == "ranking"


def test_fmt_decision_includes_substrategy():
    """Substrategy from PendingSignal propagates to decision record."""
    from bahamut.trading.selector import _fmt_decision
    sig = _make_sig(strategy="v10_mean_reversion", substrategy="v10_crash_short")
    pri = {"total": 50, "components": {}}
    d = _fmt_decision(sig, pri, "EXECUTE", ["ok"])
    assert d["substrategy"] == "v10_crash_short"


def test_class_boost_exposed_as_override_term():
    """Priority breakdown exposes class_boost_static_override AND the legacy
    class_boost key with matching values. Core check: both present."""
    from bahamut.trading.selector import _compute_priority
    sig = _make_sig(strategy="v9_breakout", asset_class="stock")
    priority = _compute_priority(sig, open_positions=[], strategy_stats={})
    bd = priority["components"]
    assert "class_boost_static_override" in bd, \
        f"expected override label, got {list(bd.keys())}"
    assert "class_boost" in bd
    assert bd["class_boost_static_override"] == 8  # v9:stock
    assert bd["class_boost"] == 8
    # Matching values — legacy alias stays in sync
    assert bd["class_boost_static_override"] == bd["class_boost"]


def test_class_boost_not_double_counted_in_total():
    """The sum that produces priority.total must exclude the override key
    to avoid double-counting (since both keys carry the same +8 for v9:stock)."""
    from bahamut.trading.selector import _compute_priority
    sig_with_boost = _make_sig(strategy="v9_breakout", asset_class="stock")
    sig_no_boost = _make_sig(strategy="v9_breakout", asset_class="forex")  # no prior
    p1 = _compute_priority(sig_with_boost, [], {})
    p2 = _compute_priority(sig_no_boost, [], {})
    # Stock version has +8 boost — total should be exactly 8 higher than forex,
    # not 16 (which would indicate double-counting).
    diff = p1["total"] - p2["total"]
    # Other factors differ (regime_quality, portfolio_fit, trust) so the
    # diff isn't exactly 8 — but it must be < 16 (= 2x boost).
    assert diff < 16, \
        f"class_boost appears double-counted: diff={diff} >= 16"


def test_class_boost_negative_prior_for_v10_crypto():
    """v10:crypto gets -10 as documented negative expectancy prior."""
    from bahamut.trading.selector import _compute_priority
    sig = _make_sig(strategy="v10_mean_reversion", asset_class="crypto")
    priority = _compute_priority(sig, open_positions=[], strategy_stats={})
    assert priority["components"].get("class_boost_static_override") == -10


def test_class_boost_absent_for_uncovered_combo():
    """v9_breakout:forex is not in the prior table — no override applied."""
    from bahamut.trading.selector import _compute_priority
    sig = _make_sig(strategy="v9_breakout", asset_class="forex")
    priority = _compute_priority(sig, open_positions=[], strategy_stats={})
    assert "class_boost_static_override" not in priority["components"]


if __name__ == "__main__":
    import sys
    tests = [
        test_fmt_decision_includes_gate_history_fields,
        test_fmt_decision_rejected_identifies_blocking_gate,
        test_fmt_decision_legacy_no_gate_history,
        test_fmt_decision_includes_substrategy,
        test_class_boost_exposed_as_override_term,
        test_class_boost_not_double_counted_in_total,
        test_class_boost_negative_prior_for_v10_crypto,
        test_class_boost_absent_for_uncovered_combo,
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
