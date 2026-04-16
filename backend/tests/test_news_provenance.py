"""
Phase 4 Item 10 — News state provenance tests.
"""
import time


def test_classify_origins_asset_specific():
    """A headline mentioning BTC directly → asset-specific."""
    from bahamut.intelligence.news_impact import _classify_news_origins
    headlines = [{
        "title": "Bitcoin rallies to new highs after ETF approval",
        "source": "reuters", "published": "2026-04-16T10:00:00Z",
    }]
    result = _classify_news_origins("BTCUSD", "crypto", headlines, [])
    assert result["asset_specific_score"] > 0
    assert result["counts_by_origin"]["asset"] == 1


def test_classify_origins_class_level():
    """Generic crypto news → class-level."""
    from bahamut.intelligence.news_impact import _classify_news_origins
    headlines = [{
        "title": "SEC approves new cryptocurrency ETF for retail investors",
        "source": "cnbc", "published": "2026-04-16T10:00:00Z",
    }]
    # SOL doesn't appear; generic 'cryptocurrency' → class-level
    result = _classify_news_origins("SOLUSD", "crypto", headlines, [])
    assert result["class_level_score"] > 0
    assert result["asset_specific_score"] == 0


def test_classify_origins_macro():
    """Fed/FOMC headline → macro."""
    from bahamut.intelligence.news_impact import _classify_news_origins
    headlines = [{
        "title": "Federal Reserve signals rate cut in September FOMC meeting",
        "source": "bloomberg", "published": "2026-04-16T10:00:00Z",
    }]
    result = _classify_news_origins("AAPL", "stock", headlines, [])
    assert result["macro_score"] > 0


def test_classify_origins_scheduled_events_are_macro():
    """Scheduled events (CPI, NFP) always count as macro."""
    from bahamut.intelligence.news_impact import _classify_news_origins
    events = [{"name": "CPI release", "importance": 3}]
    result = _classify_news_origins("BTCUSD", "crypto", [], events)
    assert result["event_macro_boost"] > 0
    assert result["macro_score"] > 0


def test_classify_origins_mixed():
    """Mix of asset + macro headlines — scores distributed."""
    from bahamut.intelligence.news_impact import _classify_news_origins
    headlines = [
        {"title": "Bitcoin price surges past $100K",
         "source": "reuters", "published": "2026-04-16T10:00:00Z"},
        {"title": "FOMC minutes reveal hawkish Fed stance",
         "source": "bloomberg", "published": "2026-04-16T10:00:00Z"},
    ]
    result = _classify_news_origins("BTCUSD", "crypto", headlines, [])
    assert result["asset_specific_score"] > 0
    assert result["macro_score"] > 0
    # Total should sum roughly to 1.0 (minus unclassified)
    total = (result["asset_specific_score"] + result["class_level_score"]
             + result["macro_score"] + result["unclassified_score"])
    assert 0.99 <= total <= 1.01, f"origins don't sum to 1: {total}"


def test_asset_news_state_has_provenance_fields():
    """AssetNewsState now carries assessment_computed_at, source_count, top_sources."""
    from bahamut.intelligence.adaptive_news_risk import AssetNewsState
    s = AssetNewsState(asset="BTCUSD")
    # Defaults present
    assert s.assessment_computed_at == 0.0
    assert s.source_count == 0
    assert s.top_sources == []
    # Can be set
    s.source_count = 3
    s.top_sources = [{"source": "reuters", "origin": "asset", "weight": 0.9}]
    assert s.source_count == 3


def test_gate_decision_includes_provenance():
    """get_news_gate_decision returns age_seconds, is_stale, origin split."""
    from bahamut.intelligence.adaptive_news_risk import (
        AssetNewsState, get_news_gate_decision,
    )
    state = AssetNewsState(
        asset="BTCUSD", mode="NORMAL",
        asset_specific=0.7, class_risk=0.2, macro_risk=0.1,
        assessment_computed_at=time.time() - 30,
        source_count=5,
    )
    d = get_news_gate_decision(state, "LONG")
    assert "age_seconds" in d
    assert "is_stale" in d
    assert "dominant_origin" in d
    assert d["dominant_origin"] == "asset"
    assert d["source_count"] == 5
    assert d["is_stale"] is False  # 30s is fresh


def test_gate_decision_flags_stale_data():
    """Data older than FRESHNESS_STALE_SEC → is_stale=True."""
    from bahamut.intelligence.adaptive_news_risk import (
        AssetNewsState, get_news_gate_decision, FRESHNESS_STALE_SEC,
    )
    state = AssetNewsState(
        asset="BTCUSD", mode="NORMAL",
        assessment_computed_at=time.time() - FRESHNESS_STALE_SEC - 60,
    )
    d = get_news_gate_decision(state, "LONG")
    assert d["is_stale"] is True


def test_gate_decision_unknown_freshness_when_never_computed():
    """assessment_computed_at=0 → age is None (never computed)."""
    from bahamut.intelligence.adaptive_news_risk import (
        AssetNewsState, get_news_gate_decision,
    )
    state = AssetNewsState(asset="BTCUSD", mode="NORMAL",
                           assessment_computed_at=0)
    d = get_news_gate_decision(state, "LONG")
    # age_seconds is None when never computed (not a real number)
    assert d["age_seconds"] is None
    # is_stale True because inf > threshold
    assert d["is_stale"] is True


def test_gate_decision_dominant_origin_none_when_no_data():
    """No origin data → dominant='none'."""
    from bahamut.intelligence.adaptive_news_risk import (
        AssetNewsState, get_news_gate_decision,
    )
    state = AssetNewsState(asset="BTCUSD", mode="NORMAL")
    d = get_news_gate_decision(state, "LONG")
    assert d["dominant_origin"] == "none"


def test_compute_adaptive_news_state_populates_provenance():
    """compute_adaptive_news_state reads origins from assessment.meta."""
    from bahamut.intelligence.adaptive_news_risk import compute_adaptive_news_state
    from bahamut.intelligence.news_impact import NewsImpactAssessment

    assessment = NewsImpactAssessment(
        asset="BTCUSD", asset_class="crypto",
        impact_score=0.5, directional_bias="LONG",
        shock_level="MEDIUM", confidence=0.7,
        headline_count=3, event_count=1,
    )
    assessment.meta = {
        "asset_specific_impact": 0.6,
        "class_risk_impact": 0.3,
        "macro_risk_impact": 0.1,
        "top_sources": [
            {"source": "reuters", "title": "BTC rallies", "origin": "asset", "weight": 0.9},
        ],
    }
    state = compute_adaptive_news_state("BTCUSD", assessment)
    assert state.asset_specific == 0.6
    assert state.class_risk == 0.3
    assert state.macro_risk == 0.1
    assert state.source_count == 4  # 3 headlines + 1 event
    assert state.assessment_computed_at > 0
    assert len(state.top_sources) == 1


def test_schema_drift_safe_missing_provenance_keys():
    """Legacy assessment without meta.origins should not crash."""
    from bahamut.intelligence.adaptive_news_risk import compute_adaptive_news_state
    from bahamut.intelligence.news_impact import NewsImpactAssessment
    assessment = NewsImpactAssessment(
        asset="BTCUSD", asset_class="crypto",
        impact_score=0.0, directional_bias="NEUTRAL",
        shock_level="NONE", confidence=0.0,
    )
    # assessment.meta defaults to {} — no origins keys at all
    state = compute_adaptive_news_state("BTCUSD", assessment)
    # All origin scores default to 0
    assert state.asset_specific == 0.0
    assert state.class_risk == 0.0
    assert state.macro_risk == 0.0


if __name__ == "__main__":
    import sys
    tests = [
        test_classify_origins_asset_specific,
        test_classify_origins_class_level,
        test_classify_origins_macro,
        test_classify_origins_scheduled_events_are_macro,
        test_classify_origins_mixed,
        test_asset_news_state_has_provenance_fields,
        test_gate_decision_includes_provenance,
        test_gate_decision_flags_stale_data,
        test_gate_decision_unknown_freshness_when_never_computed,
        test_gate_decision_dominant_origin_none_when_no_data,
        test_compute_adaptive_news_state_populates_provenance,
        test_schema_drift_safe_missing_provenance_keys,
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
