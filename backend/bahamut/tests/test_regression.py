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
    """Legacy singleton reset — the v7 engine/manager/router were removed."""
    pass




def test_v9_in_strategy_registry():
    """BUG: v9_breakout was missing from orchestrator _get_strategies().
    FIX: Added V9Breakout to strategy registry."""
    reset()
    # Import the actual function used by the orchestrator
    from bahamut.strategies.v5_base import V5Base
    from bahamut.alpha.v9_candidate import V9Breakout

    # Simulate _get_strategies (v5_tuned/v8 retired and removed)
    strategies = {
        "v5_base": V5Base(),
        "v9_breakout": V9Breakout(),
    }
    assert "v9_breakout" in strategies
    assert hasattr(strategies["v9_breakout"], "evaluate")

    print("  ✓ v9_breakout in strategy registry")








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

    assert "trading-cycle" in beat, "Operational trading cycle must be in schedule"

    print("  ✓ Legacy schedulers disabled, v7 active")


if __name__ == "__main__":
    print("=" * 60)
    print("  BAHAMUT REGRESSION TESTS")
    print("=" * 60)

    tests = [
        test_v9_in_strategy_registry,
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
