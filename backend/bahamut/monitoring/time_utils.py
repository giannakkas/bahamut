"""
Bahamut 4H Candle Timing Utilities

Standard 4H boundaries (UTC): 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
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
    # Next day 00:00
    return (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until_next_4h_close(now_utc: datetime = None) -> int:
    """Seconds until the next 4H bar closes."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    nxt = next_4h_close_utc(now_utc)
    return max(0, int((nxt - now_utc).total_seconds()))


def last_4h_close_utc(now_utc: datetime = None) -> datetime:
    """Get the most recent completed 4H bar close time."""
    return current_4h_boundary(now_utc)


def is_data_stale(last_bar_ts: str, now_utc: datetime = None, tolerance_minutes: int = 60) -> bool:
    """Check if the last bar timestamp is too old."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    if not last_bar_ts:
        return True
    try:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]:
            try:
                dt = datetime.strptime(last_bar_ts, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            dt = datetime.fromisoformat(last_bar_ts.replace("Z", "+00:00"))
        expected_last = last_4h_close_utc(now_utc)
        return (expected_last - dt).total_seconds() > tolerance_minutes * 60
    except Exception:
        return True


def get_asset_timing(last_bar_ts: str, last_processed_ts: str = "") -> dict:
    """Get full timing info for an asset.

    Args:
        last_bar_ts: Timestamp of the most recent candle from the data provider.
        last_processed_ts: Timestamp of the last bar the orchestrator actually processed.
            Used to determine if a new unprocessed bar exists.
    """
    now = datetime.now(timezone.utc)
    nxt = next_4h_close_utc(now)
    secs = seconds_until_next_4h_close(now)
    stale = is_data_stale(last_bar_ts, now) if last_bar_ts else True

    # The most recently COMPLETED 4H bar boundary
    last_completed = last_4h_close_utc(now).strftime("%Y-%m-%d %H:%M:%S")

    if stale:
        status = "STALE"
    elif not last_processed_ts:
        # No bar ever processed (fresh start) → new bar is available
        status = "NEW_BAR_READY"
    elif last_processed_ts < last_completed:
        # Last processed bar is older than the most recent completed 4H boundary
        # → a new completed bar exists that hasn't been processed
        status = "NEW_BAR_READY"
    else:
        status = "WAITING_FOR_NEW_BAR"

    return {
        "last_closed_bar": last_bar_ts or "unknown",
        "last_processed_bar": last_processed_ts or "unknown",
        "next_close": nxt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seconds_until_next_close": secs,
        "stale": stale,
        "status": status,
    }
