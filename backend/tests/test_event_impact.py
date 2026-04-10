"""Tests for Event Impact Analyzer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bahamut.intelligence.event_impact_analyzer import (
    classify_event, compute_surprise, analyze_per_asset,
    enrich_event, generate_event_id, TRACKED_ASSETS,
)


def test_classify_inflation():
    assert classify_event("US CPI YoY") == "inflation"
    assert classify_event("Core PCE Price Index") == "inflation"

def test_classify_rates():
    assert classify_event("Fed Interest Rate Decision") == "rates"
    assert classify_event("ECB Rate Decision") == "rates"

def test_classify_labor():
    assert classify_event("Non-Farm Payrolls") == "labor"
    assert classify_event("Unemployment Rate") == "labor"

def test_classify_growth():
    assert classify_event("GDP Growth Rate QoQ") == "growth"
    assert classify_event("ISM Manufacturing PMI") == "growth"

def test_classify_geopolitics():
    assert classify_event("US-China Tariff Announcement") == "geopolitics"

def test_classify_unknown():
    assert classify_event("Random Event XYZ") == "other"

def test_surprise_hotter_cpi():
    s = compute_surprise({"event": "CPI YoY", "actual": 3.5, "estimate": 3.0})
    assert s["direction"] == "hotter_than_expected"
    assert s["magnitude"] > 0

def test_surprise_cooler_cpi():
    s = compute_surprise({"event": "CPI YoY", "actual": 2.5, "estimate": 3.0})
    assert s["direction"] == "cooler_than_expected"

def test_surprise_hawkish_rate():
    s = compute_surprise({"event": "Fed Interest Rate Decision", "actual": 5.5, "estimate": 5.25})
    assert s["direction"] == "hawkish"

def test_surprise_dovish_rate():
    s = compute_surprise({"event": "Rate Decision", "actual": 4.75, "estimate": 5.0})
    assert s["direction"] == "dovish"

def test_surprise_in_line():
    s = compute_surprise({"event": "GDP", "actual": 3.0, "estimate": 3.0})
    assert s["direction"] == "in_line"

def test_surprise_no_data():
    s = compute_surprise({"event": "GDP", "actual": None, "estimate": None})
    assert s["direction"] == "unknown"

def test_per_asset_inflation_hot():
    surprise = {"direction": "hotter_than_expected", "magnitude": 0.5}
    impacts = analyze_per_asset("inflation", surprise)
    assert impacts["BTCUSD"]["arrow"] == "down"
    assert impacts["DXY"]["arrow"] == "up"
    assert impacts["XAUUSD"]["arrow"] == "down"
    assert impacts["NQ"]["arrow"] == "down"

def test_per_asset_inflation_cool():
    surprise = {"direction": "cooler_than_expected", "magnitude": 0.3}
    impacts = analyze_per_asset("inflation", surprise)
    assert impacts["BTCUSD"]["arrow"] == "up"
    assert impacts["DXY"]["arrow"] == "down"
    assert impacts["XAUUSD"]["arrow"] == "up"
    assert impacts["SPX"]["arrow"] == "up"

def test_per_asset_dovish():
    surprise = {"direction": "dovish", "magnitude": 0.4}
    impacts = analyze_per_asset("rates", surprise)
    assert impacts["BTCUSD"]["arrow"] == "up"
    assert impacts["SPX"]["arrow"] == "up"
    assert impacts["DXY"]["arrow"] == "down"

def test_per_asset_geopolitics():
    surprise = {"direction": "unknown", "magnitude": 0}
    impacts = analyze_per_asset("geopolitics", surprise)
    assert impacts["XAUUSD"]["arrow"] == "up"  # Gold is safe haven
    assert impacts["BTCUSD"]["arrow"] == "down"  # Risk-off
    assert impacts["DXY"]["arrow"] == "up"  # Flight to safety

def test_per_asset_default():
    surprise = {"direction": "unknown", "magnitude": 0}
    impacts = analyze_per_asset("other", surprise)
    for asset in TRACKED_ASSETS:
        assert impacts[asset]["arrow"] == "neutral"

def test_enrich_event_complete():
    ev = {"event": "US CPI YoY", "date": "2025-01-15", "time": "08:30",
           "country": "US", "impact": "high", "actual": 4.5, "estimate": 3.0, "prev": 3.1}
    enriched = enrich_event(ev)
    assert "id" in enriched
    assert enriched["category"] == "inflation"
    assert enriched["surprise_direction"] == "hotter_than_expected"
    assert "ai_asset_impacts" in enriched
    assert "BTCUSD" in enriched["ai_asset_impacts"]
    assert enriched["ai_asset_impacts"]["BTCUSD"]["arrow"] == "down"
    assert enriched["ai_asset_impacts"]["DXY"]["arrow"] == "up"
    assert enriched["freeze_recommended"] == True  # High impact + hot surprise
    assert enriched["ai_summary"]  # Non-empty

def test_enrich_event_no_actual():
    ev = {"event": "Non-Farm Payrolls", "date": "2025-01-10", "impact": "high",
           "actual": None, "estimate": 200}
    enriched = enrich_event(ev)
    assert enriched["surprise_direction"] == "unknown"
    assert enriched["freeze_recommended"] == True  # High impact pending

def test_event_id_stable():
    ev = {"event": "CPI", "date": "2025-01-15", "time": "08:30", "country": "US"}
    id1 = generate_event_id(ev)
    id2 = generate_event_id(ev)
    assert id1 == id2

def test_different_arrows_per_asset():
    """The same event should produce DIFFERENT arrows for different assets."""
    ev = {"event": "US CPI YoY", "date": "2025-01-15", "impact": "high",
           "actual": 4.0, "estimate": 3.2}
    enriched = enrich_event(ev)
    arrows = {a: enriched["ai_asset_impacts"][a]["arrow"] for a in TRACKED_ASSETS}
    # DXY should be opposite direction from BTC
    assert arrows["DXY"] != arrows["BTCUSD"] or arrows["DXY"] == "neutral"
    # At least 2 different arrow types
    assert len(set(arrows.values())) >= 2, f"All arrows same: {arrows}"

def test_all_tracked_assets_present():
    ev = {"event": "GDP", "date": "2025-01-15", "impact": "low"}
    enriched = enrich_event(ev)
    for asset in TRACKED_ASSETS:
        assert asset in enriched["ai_asset_impacts"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}\n  {passed} passed, {failed} failed")
    if failed: sys.exit(1)
