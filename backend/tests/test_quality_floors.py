"""Tests for quality floors — hard pre-ranking gates."""
from bahamut.trading.quality_floors import check_quality_floors, get_floors


def test_low_readiness_blocked():
    """Readiness below floor → rejected."""
    r = check_quality_floors(
        readiness_score=10, sl_pct=0.05, tp_pct=0.10,
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="PRODUCTION",
    )
    assert not r["passed"]
    assert any(f["floor"] == "readiness" for f in r["failures"])


def test_low_reward_risk_blocked():
    """R:R below floor → rejected."""
    r = check_quality_floors(
        readiness_score=80, sl_pct=0.10, tp_pct=0.05,  # 0.5:1 R:R
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="TRAINING",
    )
    assert not r["passed"]
    assert any(f["floor"] == "reward_risk" for f in r["failures"])


def test_good_candidate_passes():
    """Strong candidate passes all floors."""
    r = check_quality_floors(
        readiness_score=85, sl_pct=0.05, tp_pct=0.10,  # 2:1 R:R
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="TRAINING",
    )
    assert r["passed"]
    assert r["action"] == "pass"


def test_borderline_readiness_watchlisted_training():
    """Low readiness in training → watchlist, not reject."""
    r = check_quality_floors(
        readiness_score=20, sl_pct=0.04, tp_pct=0.10,  # Good R:R
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="TRAINING",
    )
    assert not r["passed"]
    # Training + only readiness failure → watchlist
    assert r["action"] == "watchlist"


def test_same_candidate_rejected_production():
    """Same borderline candidate in production → reject."""
    r = check_quality_floors(
        readiness_score=20, sl_pct=0.04, tp_pct=0.10,
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="PRODUCTION",
    )
    assert not r["passed"]
    assert r["action"] == "reject"


def test_floors_differ_by_mode():
    """Production floors are stricter than training."""
    t = get_floors("TRAINING")
    p = get_floors("PRODUCTION")
    assert p["min_readiness"] > t["min_readiness"]
    assert p["min_reward_risk"] > t["min_reward_risk"]
    assert p["min_effective_trust"] > t["min_effective_trust"]
    assert p["min_expectancy"] > t["min_expectancy"]


def test_multiple_failures_tracked():
    """Multiple floor failures should all be reported."""
    r = check_quality_floors(
        readiness_score=5, sl_pct=0.10, tp_pct=0.05,  # Bad readiness + bad R:R
        strategy="v9_breakout", regime="TREND", asset_class="crypto",
        asset="BTCUSD", mode="PRODUCTION",
    )
    assert not r["passed"]
    floors_hit = [f["floor"] for f in r["failures"]]
    assert "readiness" in floors_hit
    assert "reward_risk" in floors_hit


if __name__ == "__main__":
    tests = [
        test_low_readiness_blocked, test_low_reward_risk_blocked,
        test_good_candidate_passes, test_borderline_readiness_watchlisted_training,
        test_same_candidate_rejected_production, test_floors_differ_by_mode,
        test_multiple_failures_tracked,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
