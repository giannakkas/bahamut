"""
Bahamut Strategy Condition Snapshots

Computes and exposes the exact conditions each strategy checks,
with actual vs target values, for observability.
Does NOT change strategy logic — reads the same indicators.
"""
import structlog

logger = structlog.get_logger()

# Store latest snapshots per asset
_snapshots: dict[str, dict] = {}


def compute_conditions(asset: str, candles: list[dict], indicators: dict,
                       prev_indicators: dict, regime: str) -> list[dict]:
    """Compute condition snapshots for all strategies on an asset."""
    results = []

    close = indicators.get("close", 0)
    ema20 = indicators.get("ema_20", 0)
    ema50 = indicators.get("ema_50", 0)
    ema200 = indicators.get("ema_200", 0)

    prev_ema20 = prev_indicators.get("ema_20", 0) if prev_indicators else 0
    prev_ema50 = prev_indicators.get("ema_50", 0) if prev_indicators else 0

    # ── v5_base / v5_tuned ──
    for strat in ["v5_base", "v5_tuned"]:
        regime_ok = regime == "TREND"
        above_ema200 = close > ema200 if ema200 > 0 else False
        cross = ema20 > ema50 and prev_ema20 <= prev_ema50 if (ema20 and ema50 and prev_ema20 and prev_ema50) else False
        ema20_above = ema20 > ema50

        conditions = [
            {
                "name": "Regime is TREND",
                "passed": regime_ok,
                "actual": regime,
                "target": "TREND",
            },
            {
                "name": "Price above EMA200",
                "passed": above_ema200,
                "actual": f"${close:,.0f}",
                "target": f"> ${ema200:,.0f}" if ema200 else "N/A",
                "distance": f"{((close - ema200) / ema200 * 100):+.1f}%" if ema200 > 0 else "N/A",
            },
            {
                "name": "EMA20 × EMA50 golden cross",
                "passed": cross,
                "actual": f"EMA20=${ema20:,.0f}, EMA50=${ema50:,.0f}",
                "target": "EMA20 crosses above EMA50",
                "distance": f"{((ema20 - ema50) / ema50 * 100):+.2f}%" if ema50 > 0 else "N/A",
            },
        ]

        all_pass = regime_ok and above_ema200 and cross
        if not regime_ok:
            reason = f"regime is {regime}, need TREND"
        elif not above_ema200:
            reason = f"price ${close:,.0f} below EMA200 ${ema200:,.0f}"
        elif not cross:
            if ema20_above:
                reason = "EMA20 already above EMA50 (no new cross)"
            else:
                reason = f"EMA20 ${ema20:,.0f} below EMA50 ${ema50:,.0f}"
        else:
            reason = "all conditions met — signal generated"

        results.append({
            "strategy": strat,
            "eligible": all_pass,
            "result": "SIGNAL" if all_pass else "NO_SIGNAL",
            "reason": reason,
            "conditions": conditions,
        })

    # ── v9_breakout ──
    high_20 = max(c.get("high", 0) for c in candles[-21:-1]) if len(candles) > 21 else 0
    above_breakout = close > high_20 if high_20 > 0 else False

    # Count confirmation bars
    confirm_count = 0
    if above_breakout and len(candles) >= 4:
        for i in range(-3, 0):
            if candles[i].get("close", 0) > high_20:
                confirm_count += 1

    confirmed = confirm_count >= 3
    regime_allows = regime in ("TREND",)

    v9_conditions = [
        {
            "name": "Regime allows breakout",
            "passed": regime_allows,
            "actual": regime,
            "target": "TREND",
        },
        {
            "name": "Price above 20-bar high",
            "passed": above_breakout,
            "actual": f"${close:,.0f}",
            "target": f"> ${high_20:,.0f}" if high_20 > 0 else "N/A",
            "distance": f"${close - high_20:+,.0f} ({((close - high_20) / high_20 * 100):+.1f}%)" if high_20 > 0 else "N/A",
        },
        {
            "name": "3-bar confirmation hold",
            "passed": confirmed,
            "actual": f"{confirm_count}/3 bars confirmed",
            "target": "3/3",
        },
    ]

    all_v9 = regime_allows and above_breakout and confirmed
    if not regime_allows:
        v9_reason = f"regime is {regime}, need TREND"
    elif not above_breakout:
        v9_reason = f"price ${close:,.0f} below 20-bar high ${high_20:,.0f}"
    elif not confirmed:
        v9_reason = f"breakout not confirmed ({confirm_count}/3 bars)"
    else:
        v9_reason = "breakout confirmed — signal generated"

    results.append({
        "strategy": "v9_breakout",
        "eligible": all_v9,
        "result": "SIGNAL" if all_v9 else "NO_SIGNAL",
        "reason": v9_reason,
        "conditions": v9_conditions,
    })

    # Store snapshot
    _snapshots[asset] = {
        "asset": asset,
        "regime": regime,
        "price": close,
        "strategies": results,
    }

    # Also persist to Redis for Celery worker → FastAPI cross-process reads
    try:
        import redis, os, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.hset("bahamut:strategy_conditions", asset, json.dumps(_snapshots[asset]))
    except Exception:
        pass

    return results


def get_latest_snapshots() -> dict:
    """Get most recent strategy condition snapshots for all assets."""
    # In-memory first (same process — works with --workers 1)
    if _snapshots:
        return dict(_snapshots)
    # Fallback: Redis (for when Celery worker wrote the data)
    try:
        import redis, os, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.hgetall("bahamut:strategy_conditions")
        if raw:
            return {(k.decode() if isinstance(k, bytes) else k): json.loads(v) for k, v in raw.items()}
    except Exception:
        pass
    return {}


def get_asset_snapshot(asset: str) -> dict:
    """Get snapshot for a specific asset."""
    return _snapshots.get(asset, {})
