"""
Bahamut 4H Candle Timing Utilities

Standard 4H boundaries (UTC): 00:00, 04:00, 08:00, 12:00, 16:00, 20:00

NOTE: For data freshness decisions, use monitoring/data_health.py.
      This module provides timing utilities only.
"""
from datetime import datetime, timezone, timedelta

FOUR_HOUR_BOUNDARIES = [0, 4, 8, 12, 16, 20]


def current_4h_boundary(now_utc: datetime = None) -> datetime:
    """Get the start of the current 4H window."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    boundary_hour = max(h for h in FOUR_HOUR_BOUNDARIES if h <= hour)
    return now_utc.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)


def next_4h_close_utc(now_utc: datetime = None) -> datetime:
    """Get the next 4H bar close time."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    for h in FOUR_HOUR_BOUNDARIES:
        if h > hour:
            return now_utc.replace(hour=h, minute=0, second=0, microsecond=0)
    return (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until_next_4h_close(now_utc: datetime = None) -> int:
    """Seconds until the next 4H bar closes."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    nxt = next_4h_close_utc(now_utc)
    return max(0, int((nxt - now_utc).total_seconds()))


def last_4h_close_utc(now_utc: datetime = None) -> datetime:
    """Get the most recent completed 4H bar close time.
    This equals current_4h_boundary (start of current window = close of previous bar)."""
    return current_4h_boundary(now_utc)


def is_data_stale(last_bar_ts: str, now_utc: datetime = None, tolerance_minutes: int = 60) -> bool:
    """Check if the last bar timestamp is too old.

    IMPORTANT: Accounts for bar-open timestamp convention.
    TwelveData returns bar OPEN time. A 4H bar closing at 20:00 has ts "16:00".
    The expected last completed bar OPEN is current_4h_boundary - 4h.
    """
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    if not last_bar_ts:
        return True
    try:
        from bahamut.monitoring.data_health import evaluate_asset_health
        health = evaluate_asset_health(last_bar_ts, now_utc)
        return health["status"] in ("STALE", "MISSING")
    except Exception:
        # Fallback: simple check
        return True


def get_asset_timing(last_bar_ts: str, last_processed_ts: str = "", now_utc: datetime = None) -> dict:
    """Get full timing info for an asset. Delegates freshness to canonical module."""
    now = now_utc or datetime.now(timezone.utc)
    nxt = next_4h_close_utc(now)
    secs = seconds_until_next_4h_close(now)

    # Use canonical health evaluation
    try:
        from bahamut.monitoring.data_health import evaluate_asset_health
        health = evaluate_asset_health(last_bar_ts, now)
        stale = health["status"] in ("STALE", "MISSING")
    except Exception:
        stale = True
        health = {"status": "MISSING", "reason": "evaluation failed"}

    last_completed = last_4h_close_utc(now).strftime("%Y-%m-%d %H:%M:%S")

    if stale:
        status = "STALE"
    elif not last_processed_ts or last_processed_ts == "unknown":
        status = "NEW_BAR_READY"
    elif last_processed_ts < last_completed:
        status = "NEW_BAR_READY"
    else:
        status = "WAITING"

    return {
        "last_closed_bar": last_bar_ts or "unknown",
        "last_processed_bar": last_processed_ts or "unknown",
        "next_close": nxt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seconds_until_next_close": secs,
        "stale": stale,
        "status": status,
        "data_health": health.get("status", "UNKNOWN"),
        "data_reason": health.get("reason", ""),
        "can_trade": health.get("can_trade", False),
    }
