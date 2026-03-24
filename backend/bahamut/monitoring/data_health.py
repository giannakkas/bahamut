"""
Bahamut.AI — Canonical Data Health Module

SINGLE SOURCE OF TRUTH for all data freshness decisions.

Every consumer — dashboard, orchestrator, alerts, system_readiness —
calls evaluate_asset_health() or get_data_health() from this module.
Nobody computes freshness independently.

Bar timestamp convention:
  Twelve Data returns BAR OPEN time. A 4H bar spanning 16:00-20:00 UTC
  has timestamp "2026-03-22 16:00:00". This is standard for all providers.

Freshness logic:
  Given now_utc, the expected latest bar open is current_4h_boundary(now).
  This is the CURRENT (possibly incomplete) bar. The last COMPLETED bar
  open is current_4h_boundary(now) - 4h.

  HEALTHY:  latest candle >= last_completed_bar_open (within tolerance)
  DEGRADED: latest candle = one bar behind (4-8h old boundary-wise)
  STALE:    latest candle > 8h behind expected
  MISSING:  no candles at all

Crypto: 24/7 market, no weekend logic, no session logic.
"""
import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()

BAR_DURATION_HOURS = 4
FOUR_HOUR_BOUNDARIES = [0, 4, 8, 12, 16, 20]


# ═══════════════════════════════════════════
# 4H BOUNDARY CALCULATIONS
# ═══════════════════════════════════════════

def current_4h_boundary(now_utc: datetime = None) -> datetime:
    """Start of the current 4H window (= close of previous bar)."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    boundary_hour = max(h for h in FOUR_HOUR_BOUNDARIES if h <= hour)
    return now_utc.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)


def previous_4h_boundary(now_utc: datetime = None) -> datetime:
    """Start of the PREVIOUS 4H window (= open of last completed bar).
    This is the timestamp that TwelveData returns for the last completed bar."""
    return current_4h_boundary(now_utc) - timedelta(hours=BAR_DURATION_HOURS)


def next_4h_close(now_utc: datetime = None) -> datetime:
    """Next 4H bar close time."""
    if not now_utc:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    for h in FOUR_HOUR_BOUNDARIES:
        if h > hour:
            return now_utc.replace(hour=h, minute=0, second=0, microsecond=0)
    return (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# ═══════════════════════════════════════════
# TIMESTAMP PARSING
# ═══════════════════════════════════════════

def parse_bar_timestamp(ts: str) -> datetime | None:
    """Parse a bar timestamp string to timezone-aware datetime."""
    if not ts or ts == "unknown":
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]:
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


# ═══════════════════════════════════════════
# CANONICAL HEALTH EVALUATION
# ═══════════════════════════════════════════

def evaluate_asset_health(
    last_candle_ts: str,
    now_utc: datetime = None,
) -> dict:
    """
    Canonical data freshness evaluation for one asset.

    Args:
        last_candle_ts: Timestamp of the most recent candle from the provider
                        (bar OPEN time, as returned by Twelve Data).
        now_utc: Current time (for testing). Defaults to now.

    Returns:
        {
            "status": "HEALTHY" | "DEGRADED" | "STALE" | "MISSING",
            "reason": str,
            "last_candle_ts": str,
            "expected_bar_open": str,       # expected last completed bar open
            "current_bar_open": str,        # current (incomplete) bar open
            "lag_seconds": int | None,      # how far behind expected
            "lag_bars": int | None,         # how many 4H bars behind
            "can_trade": bool,              # whether new entries are allowed
        }
    """
    if not now_utc:
        now_utc = datetime.now(timezone.utc)

    result = {
        "last_candle_ts": last_candle_ts or "none",
        "current_bar_open": current_4h_boundary(now_utc).strftime("%Y-%m-%d %H:%M:%S"),
        "expected_bar_open": previous_4h_boundary(now_utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not last_candle_ts:
        return {**result, "status": "MISSING", "reason": "no candle data",
                "lag_seconds": None, "lag_bars": None, "can_trade": False}

    bar_dt = parse_bar_timestamp(last_candle_ts)
    if bar_dt is None:
        return {**result, "status": "MISSING", "reason": f"unparseable timestamp: {last_candle_ts}",
                "lag_seconds": None, "lag_bars": None, "can_trade": False}

    # Expected: the current bar open (this is the most recent bar TwelveData might return)
    current_bar = current_4h_boundary(now_utc)
    # The last COMPLETED bar's open time
    last_completed_bar = previous_4h_boundary(now_utc)

    # How far behind is the latest candle?
    # If bar_dt >= current_bar → we have the current (incomplete) bar → very fresh
    # If bar_dt >= last_completed_bar → we have the last completed bar → healthy
    # If bar_dt < last_completed_bar → we're behind

    if bar_dt >= current_bar:
        # We have the current (in-progress) bar — freshest possible
        lag = 0
        lag_bars = 0
        status = "HEALTHY"
        reason = "have current bar"
    elif bar_dt >= last_completed_bar:
        # We have the last completed bar — this is normal and healthy
        lag = int((current_bar - bar_dt).total_seconds())
        lag_bars = 0
        status = "HEALTHY"
        reason = "have last completed bar"
    else:
        # We're behind — how many bars?
        lag = int((last_completed_bar - bar_dt).total_seconds())
        lag_bars = lag // (BAR_DURATION_HOURS * 3600)

        if lag_bars <= 1:
            # 1 bar behind (4-8h) — degraded but possibly just a provider delay
            status = "DEGRADED"
            reason = f"{lag_bars + 1} bars behind ({lag // 3600}h)"
        else:
            # 2+ bars behind — stale
            status = "STALE"
            reason = f"{lag_bars + 1} bars behind ({lag // 3600}h)"

    can_trade = status == "HEALTHY"

    return {
        **result,
        "status": status,
        "reason": reason,
        "lag_seconds": lag,
        "lag_bars": lag_bars,
        "can_trade": can_trade,
    }


def get_data_health(now_utc: datetime = None) -> dict:
    """
    Get comprehensive data health for all assets.
    This is the ONE function that dashboard, alerts, and orchestrator should call.
    """
    if not now_utc:
        now_utc = datetime.now(timezone.utc)

    from bahamut.data.live_data import get_data_source, get_data_status, get_last_bar_timestamp

    source = get_data_source()
    data_status = get_data_status()

    assets = {}
    worst_status = "HEALTHY"
    status_rank = {"HEALTHY": 0, "DEGRADED": 1, "STALE": 2, "MISSING": 3}

    for asset in ["BTCUSD", "ETHUSD"]:
        # Get the last candle timestamp from the data provider (via Redis)
        provider_info = data_status.get(asset, {})
        last_candle = ""
        if isinstance(provider_info, dict):
            last_candle = provider_info.get("detail", "")
            # detail might be the timestamp or a message — check format
            if last_candle and not any(c.isdigit() for c in last_candle[:4]):
                last_candle = ""  # not a timestamp

        # Fall back to last processed bar if no provider timestamp available
        if not last_candle:
            last_candle = get_last_bar_timestamp(asset)

        health = evaluate_asset_health(last_candle, now_utc)
        assets[asset] = health

        if status_rank.get(health["status"], 3) > status_rank.get(worst_status, 0):
            worst_status = health["status"]

    can_trade_any = any(a["can_trade"] for a in assets.values())
    can_trade_all = all(a["can_trade"] for a in assets.values())

    return {
        "status": worst_status,
        "source": source,
        "can_trade_any": can_trade_any,
        "can_trade_all": can_trade_all,
        "assets": assets,
        "next_4h_close": next_4h_close(now_utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seconds_until_next_close": max(0, int((next_4h_close(now_utc) - now_utc).total_seconds())),
    }
