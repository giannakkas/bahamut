"""
Phase 4 Item 11 — AI posture source transparency tests.
"""
import os
import time


def _reset_module():
    """Clear module globals between tests."""
    import bahamut.intelligence.ai_market_analyst as a
    a._analysis_cache = None
    a._analysis_cache_ts = 0
    a._stale_cache = None
    a._stale_cache_ts = 0


def test_get_analysis_source_disabled_when_no_api_key():
    _reset_module()
    from bahamut.intelligence.ai_market_analyst import get_analysis_source
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        analysis, source = get_analysis_source()
        assert analysis is None
        assert source == "disabled"
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)


def test_get_analysis_source_fallback_when_no_cache():
    _reset_module()
    from bahamut.intelligence.ai_market_analyst import get_analysis_source
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        analysis, source = get_analysis_source()
        assert analysis is None
        assert source == "fallback_rules"
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_get_analysis_source_fresh():
    """Cache populated within FRESH_TTL → source='fresh'."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        a._analysis_cache = {"posture": "AGGRESSIVE", "crypto_mode": "NORMAL"}
        a._analysis_cache_ts = time.time() - 10  # 10s old → fresh
        analysis, source = a.get_analysis_source()
        assert analysis["posture"] == "AGGRESSIVE"
        assert source == "fresh"
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_get_analysis_source_stale():
    """Cache populated but older than FRESH_TTL → source='stale'."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        a._analysis_cache = {"posture": "DEFENSIVE", "crypto_mode": "CAUTION"}
        a._analysis_cache_ts = time.time() - (a.FRESH_TTL + 30)  # past fresh, within stale
        analysis, source = a.get_analysis_source()
        assert analysis["posture"] == "DEFENSIVE"
        assert source == "stale"
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_get_ai_decision_returns_canonical_source_field():
    """get_ai_decision exposes ai_source field."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        a._analysis_cache = {
            "posture": "AGGRESSIVE", "crypto_mode": "NORMAL",
            "stocks_mode": "NORMAL", "global_size_multiplier": 1.0,
            "crypto_longs_allowed": True, "crypto_shorts_allowed": True,
            "stock_longs_allowed": True, "stock_shorts_allowed": True,
        }
        a._analysis_cache_ts = time.time() - 5
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        assert "ai_source" in d
        assert d["ai_source"] == "fresh"
        assert "ai_cache_age_seconds" in d
        assert d["ai_cache_age_seconds"] is not None
        assert d["ai_cache_age_seconds"] < 60
        assert "ai_posture_softened" in d
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_legacy_source_string_distinguishes_stale_from_fresh():
    """_source legacy field reflects fresh vs stale."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        a._analysis_cache = {"posture": "DEFENSIVE"}
        a._analysis_cache_ts = time.time() - (a.FRESH_TTL + 30)
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        assert d["_source"] == "opus-4.6-stale"
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_stale_posture_softens_penalty():
    """Stale DEFENSIVE posture should soften penalty (e.g. -3 → -1)."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        # Fresh DEFENSIVE → -3 penalty
        a._analysis_cache = {
            "posture": "DEFENSIVE", "crypto_mode": "NORMAL",
            "global_size_multiplier": 1.0,
            "crypto_longs_allowed": True, "crypto_shorts_allowed": True,
        }
        a._analysis_cache_ts = time.time() - 5
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        fresh = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        fresh_penalty = fresh["asset_decision"]["threshold_penalty"]
        assert fresh_penalty == -3
        assert fresh["ai_posture_softened"] is False

        # Now stale: same posture
        a._analysis_cache_ts = time.time() - (a.FRESH_TTL + 30)
        stale = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        stale_penalty = stale["asset_decision"]["threshold_penalty"]
        # Softened: -3 → max(-3, -3//2) = max(-3, -1) = -1
        assert stale_penalty > fresh_penalty, \
            f"stale penalty {stale_penalty} should be softer than fresh {fresh_penalty}"
        assert stale["ai_posture_softened"] is True
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_fallback_source_when_no_cache():
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        assert d["ai_source"] == "fallback_rules"
        assert d["_fallback_used"] is True
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_disabled_source_when_no_api_key():
    _reset_module()
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        assert d["ai_source"] == "disabled"
        assert d["_fallback_used"] is True
        assert d["_source"] == "rule-based-disabled"
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)


def test_fresh_posture_no_softening():
    """Fresh posture → softened=False."""
    import bahamut.intelligence.ai_market_analyst as a
    _reset_module()
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        a._analysis_cache = {
            "posture": "FROZEN", "crypto_mode": "FROZEN",
            "global_size_multiplier": 0.25,
            "crypto_longs_allowed": False, "crypto_shorts_allowed": False,
        }
        a._analysis_cache_ts = time.time() - 5
        from bahamut.intelligence.ai_decision_service import get_ai_decision
        d = get_ai_decision("BTCUSD", "crypto", "v9_breakout", "LONG")
        assert d["ai_source"] == "fresh"
        assert d["ai_posture_softened"] is False
        # Fresh FROZEN: full -4 penalty applied
        assert d["asset_decision"]["threshold_penalty"] == -4
    finally:
        _reset_module()
        os.environ.pop("ANTHROPIC_API_KEY", None)


if __name__ == "__main__":
    import sys
    tests = [
        test_get_analysis_source_disabled_when_no_api_key,
        test_get_analysis_source_fallback_when_no_cache,
        test_get_analysis_source_fresh,
        test_get_analysis_source_stale,
        test_get_ai_decision_returns_canonical_source_field,
        test_legacy_source_string_distinguishes_stale_from_fresh,
        test_stale_posture_softens_penalty,
        test_fallback_source_when_no_cache,
        test_disabled_source_when_no_api_key,
        test_fresh_posture_no_softening,
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
