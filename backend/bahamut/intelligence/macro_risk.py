"""
Bahamut Macro Risk — real global-macro regime from FRED.

Pulls VIX (equity fear gauge) and US Treasury yields (2Y/10Y) from the FRED
API and derives a market-wide RISK STATE that gently scales position size:

    risk_on / neutral  → size ×1.00
    risk_off           → size ×0.75   (VIX 30–40)
    risk_off_extreme   → block new entries (VIX ≥ 40, rare crisis level)

Design principles:
  - SOFT by default. It scales size, it does not pick direction or hard-gate
    (except the extreme VIX≥40 crash guard). Macro filters that hard-block
    tend to hurt returns; a size taper lets the learning engine keep sampling.
  - FAIL SAFE. Any error, missing FRED key, or unavailable series returns a
    NEUTRAL state (multiplier 1.0, no block), so this overlay can never stop
    trading by failing.
  - Cached in Redis (~3h). FRED series are daily, so this is plenty fresh.

Requires FRED_API_KEY (Railway env / settings.fred_api_key). Without it the
module no-ops (multiplier 1.0) and reports source="no_fred_key".
"""
import json
import urllib.request
import urllib.parse
import structlog

logger = structlog.get_logger()

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_KEY = "bahamut:macro:state"
_CACHE_TTL = 3 * 3600  # 3h — FRED series update daily

# Risk state → position-size multiplier
_STATE_MULT = {
    "risk_on": 1.0,
    "neutral": 1.0,
    "risk_off": 0.75,
    "risk_off_extreme": 0.5,  # also sets block_new
}

NEUTRAL = {
    "vix": None, "us10y": None, "us2y": None, "curve_spread": None,
    "curve_inverted": False, "risk_state": "neutral", "size_multiplier": 1.0,
    "block_new": False, "source": "unavailable",
}


def _get_redis():
    import os
    import redis
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def _fred_latest(series_id: str, api_key: str):
    """Return the most recent non-missing observation for a FRED series."""
    try:
        q = urllib.parse.urlencode({
            "series_id": series_id, "api_key": api_key, "file_type": "json",
            "sort_order": "desc", "limit": 10,
        })
        req = urllib.request.Request(_FRED_URL + "?" + q)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for obs in data.get("observations", []):
            v = obs.get("value", ".")
            if v not in (".", "", None):
                return float(v)
    except Exception as e:
        logger.warning("fred_fetch_failed", series=series_id, error=str(e)[:120])
    return None


def _classify(vix: float) -> str:
    if vix < 20:
        return "risk_on"
    if vix < 30:
        return "neutral"
    if vix < 40:
        return "risk_off"
    return "risk_off_extreme"


def get_macro_state(force: bool = False) -> dict:
    """Fetch (cached) global macro risk state. Always returns a dict; never raises."""
    r = _get_redis()
    if r and not force:
        try:
            raw = r.get(_CACHE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass

    try:
        from bahamut.config import get_settings
        api_key = get_settings().fred_api_key
    except Exception:
        api_key = ""

    if not api_key:
        return dict(NEUTRAL, source="no_fred_key")

    vix = _fred_latest("VIXCLS", api_key)
    us10y = _fred_latest("DGS10", api_key)
    us2y = _fred_latest("DGS2", api_key)

    if vix is None:
        # Couldn't read the fear gauge — stay neutral but keep any yields we got.
        state = dict(NEUTRAL, us10y=us10y, us2y=us2y, source="fred_partial")
    else:
        risk = _classify(vix)
        spread = round(us10y - us2y, 2) if (us10y is not None and us2y is not None) else None
        state = {
            "vix": vix,
            "us10y": us10y,
            "us2y": us2y,
            "curve_spread": spread,
            "curve_inverted": (spread is not None and spread < 0),
            "risk_state": risk,
            "size_multiplier": _STATE_MULT[risk],
            "block_new": (risk == "risk_off_extreme"),
            "source": "fred",
        }

    if r:
        try:
            r.set(_CACHE_KEY, json.dumps(state), ex=_CACHE_TTL)
        except Exception:
            pass
    return state


def get_macro_size_multiplier() -> float:
    """Position-size multiplier from the current macro regime (1.0 = neutral)."""
    try:
        return float(get_macro_state().get("size_multiplier", 1.0))
    except Exception:
        return 1.0


def macro_blocks_new_entries() -> bool:
    """True only in extreme risk-off (VIX >= 40) — a crisis crash guard."""
    try:
        return bool(get_macro_state().get("block_new", False))
    except Exception:
        return False
