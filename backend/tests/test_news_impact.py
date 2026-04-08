"""
Tests for the News Impact Intelligence Module.

Covers:
  - Scheduled event freeze
  - Positive / negative surprise
  - Conflicting headlines
  - Stale news decay
  - Extreme shock hard block
  - Aligned news boosting consensus
  - Opposing news reducing consensus
  - Headline deduplication
  - Source credibility mapping
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bahamut.intelligence.news_impact import (
    recency_weight,
    source_credibility,
    headline_severity,
    event_surprise_score,
    scheduled_event_component,
    headline_component,
    compute_news_impact,
    compute_consensus_modifier,
    dedupe_headlines,
    NewsImpactAssessment,
)
from datetime import datetime, timezone, timedelta


def test_recency_weight_fresh():
    """Fresh headline should have high weight."""
    now = datetime.now(timezone.utc).isoformat()
    w = recency_weight(now)
    assert w > 0.9, f"Fresh headline should be >0.9, got {w}"


def test_recency_weight_stale():
    """4-hour-old headline should decay significantly."""
    old = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    w = recency_weight(old)
    assert w < 0.3, f"4h old headline should be <0.3, got {w}"


def test_recency_weight_empty():
    """Empty string should return low weight."""
    w = recency_weight("")
    assert w == 0.0


def test_source_credibility_tier1():
    """Reuters should have high credibility."""
    assert source_credibility("Reuters") >= 0.85


def test_source_credibility_tier2():
    """CNBC should have decent credibility."""
    assert source_credibility("CNBC") >= 0.7


def test_source_credibility_unknown():
    """Unknown source should have low credibility."""
    assert source_credibility("random_blog_xyz") <= 0.5


def test_headline_severity_bullish():
    """Bullish headline with 'rate cut' should score bullish."""
    sev = headline_severity("Fed announces rate cut amid easing concerns")
    assert sev["direction"] == "LONG"
    assert sev["bullish"] > 0.5


def test_headline_severity_bearish():
    """Bearish headline with 'recession' should score bearish."""
    sev = headline_severity("Markets fear recession as trade war escalates")
    assert sev["direction"] == "SHORT"
    assert sev["bearish"] > 0.5


def test_headline_severity_shock():
    """Shock headline should score high shock."""
    sev = headline_severity("Emergency: Exchange halted all trading")
    assert sev["shock"] > 0.7


def test_headline_severity_neutral():
    """Neutral headline should not trigger strong direction."""
    sev = headline_severity("Markets close flat on light volume today")
    assert sev["severity"] < 0.3


def test_event_surprise_positive():
    """GDP beat should be bullish."""
    ev = {"event": "GDP Growth Rate", "actual": 3.2, "estimate": 2.5}
    s = event_surprise_score(ev)
    assert s["direction"] == "LONG"
    assert s["surprise_z"] > 0.2
    assert s["magnitude"] != "NONE"


def test_event_surprise_negative():
    """Unemployment miss (higher than expected) should be bearish."""
    ev = {"event": "Unemployment Rate", "actual": 5.2, "estimate": 4.5}
    s = event_surprise_score(ev)
    assert s["direction"] == "SHORT"  # Higher unemployment = bearish
    assert s["surprise_z"] > 0.1


def test_event_surprise_inflation_higher():
    """Higher CPI (inflation) should be bearish."""
    ev = {"event": "CPI Inflation YoY", "actual": 4.5, "estimate": 3.5}
    s = event_surprise_score(ev)
    assert s["direction"] == "SHORT"  # Higher inflation = bearish


def test_event_surprise_no_data():
    """Event without actual data should return neutral."""
    ev = {"event": "FOMC Decision", "actual": None, "estimate": None}
    s = event_surprise_score(ev)
    assert s["direction"] == "NEUTRAL"
    assert s["surprise_z"] == 0


def test_scheduled_event_freeze():
    """High-impact event within freeze window should trigger freeze."""
    events = [{
        "event": "Non-Farm Payrolls",
        "impact": "high",
        "time": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "actual": None, "estimate": None,
    }]
    result = scheduled_event_component(events, "EURUSD", "fx")
    assert result["freeze"] is True
    assert "NFP" in result["freeze_reason"] or "Non-Farm" in result["freeze_reason"]


def test_scheduled_event_no_freeze():
    """Low-impact event should not freeze."""
    events = [{
        "event": "MBA Mortgage Applications",
        "impact": "low",
        "time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "actual": None, "estimate": None,
    }]
    result = scheduled_event_component(events, "EURUSD", "fx")
    assert result["freeze"] is False


def test_headline_component_cluster():
    """Multiple same-direction headlines should get cluster bonus."""
    now = datetime.now(timezone.utc).isoformat()
    headlines = [
        {"title": "Fed announces rate cut", "source": "Reuters", "published": now},
        {"title": "Markets rally on dovish guidance", "source": "Bloomberg", "published": now},
        {"title": "Growth beats expectations across sectors", "source": "CNBC", "published": now},
        {"title": "Rate cut expectations boost equities", "source": "WSJ", "published": now},
    ]
    result = headline_component(headlines)
    assert result["direction"] == "LONG"
    assert result["cluster_bonus"] > 0


def test_headline_component_conflict():
    """Conflicting headlines should get conflict penalty."""
    now = datetime.now(timezone.utc).isoformat()
    headlines = [
        {"title": "Fed announces rate cut", "source": "Reuters", "published": now},
        {"title": "Markets crash on recession fears", "source": "Bloomberg", "published": now},
        {"title": "Growth surges past expectations", "source": "CNBC", "published": now},
        {"title": "War threatens global trade collapse", "source": "WSJ", "published": now},
    ]
    result = headline_component(headlines)
    assert result["conflict_penalty"] > 0


def test_compute_news_impact_high():
    """Extreme event + strong headlines should produce high impact."""
    now = datetime.now(timezone.utc)
    events = [{
        "event": "Non-Farm Payrolls",
        "impact": "high",
        "time": (now - timedelta(minutes=5)).isoformat(),
        "actual": 350, "estimate": 200, "prev": 180,
    }]
    headlines = [
        {"title": "NFP beats expectations massively, surge in jobs", "source": "Reuters", "published": now.isoformat()},
        {"title": "Employment growth surges past forecasts", "source": "Bloomberg", "published": now.isoformat()},
    ]
    nia = compute_news_impact("EURUSD", "fx", headlines, events)
    assert nia.impact_score > 0.3
    assert nia.shock_level != "NONE"


def test_compute_news_impact_empty():
    """No news + no events = zero impact."""
    nia = compute_news_impact("BTCUSD", "crypto", [], [])
    assert nia.impact_score == 0
    assert nia.shock_level == "NONE"
    assert nia.freeze_trading is False


def test_extreme_shock_freeze():
    """Extreme shock should trigger trading freeze."""
    now = datetime.now(timezone.utc)
    headlines = [
        {"title": "Emergency: Exchange bankruptcy, all funds frozen", "source": "Reuters", "published": now.isoformat()},
        {"title": "Flash crash liquidation across all markets", "source": "Bloomberg", "published": now.isoformat()},
        {"title": "Panic selloff as emergency halt triggers", "source": "CNBC", "published": now.isoformat()},
    ]
    events = [{
        "event": "Emergency Rate Decision",
        "impact": "high",
        "time": now.isoformat(),
        "actual": 8.0, "estimate": 3.0,  # Massive surprise (z > 1.5)
    }]
    nia = compute_news_impact("BTCUSD", "crypto", headlines, events)
    # With extreme headlines + massive event surprise + freeze window = should freeze
    assert nia.freeze_trading is True


def test_consensus_modifier_aligned():
    """News aligned with trade should boost priority."""
    nia = NewsImpactAssessment(
        asset="BTCUSD", asset_class="crypto",
        impact_score=0.6, directional_bias="LONG",
        confidence=0.8,
    )
    mod = compute_consensus_modifier(nia, "LONG")
    assert mod["modifier"] > 0
    assert mod["action"] == "boost"


def test_consensus_modifier_opposed():
    """News opposing trade should penalize priority."""
    nia = NewsImpactAssessment(
        asset="BTCUSD", asset_class="crypto",
        impact_score=0.6, directional_bias="SHORT",
        confidence=0.8,
    )
    mod = compute_consensus_modifier(nia, "LONG")
    assert mod["modifier"] < 0
    assert mod["action"] == "penalize"


def test_consensus_modifier_freeze():
    """Frozen trading should return freeze action."""
    nia = NewsImpactAssessment(
        asset="EURUSD", asset_class="fx",
        impact_score=0.8, freeze_trading=True,
        freeze_reason="CPI event in 5min",
    )
    mod = compute_consensus_modifier(nia, "LONG")
    assert mod["action"] == "freeze"
    assert mod["modifier"] < 0


def test_consensus_modifier_low_impact():
    """Low impact should return neutral."""
    nia = NewsImpactAssessment(
        asset="BTCUSD", asset_class="crypto",
        impact_score=0.05, directional_bias="LONG",
    )
    mod = compute_consensus_modifier(nia, "LONG")
    assert mod["modifier"] == 0
    assert mod["action"] == "neutral"


def test_dedupe_headlines():
    """Duplicate headlines across sources should be deduped."""
    headlines = [
        {"title": "Fed cuts rates by 25 basis points", "source": "Reuters"},
        {"title": "Fed cuts rates by 25 basis points", "source": "Bloomberg"},
        {"title": "Markets react to Fed rate decision", "source": "CNBC"},
    ]
    unique = dedupe_headlines(headlines)
    assert len(unique) == 2


def test_stale_news_decay():
    """Headlines from 8 hours ago should have minimal impact."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    headlines = [
        {"title": "Markets crash on recession fears", "source": "Reuters", "published": stale},
    ]
    nia = compute_news_impact("BTCUSD", "crypto", headlines, [])
    # Stale headline should have very low impact due to decay
    assert nia.impact_score < 0.1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)
