"""
Bahamut.AI — Crypto Fear & Greed Index (Alternative.me)

100% free, no API key, no rate limits.
Industry standard crypto market sentiment metric.

API: https://api.alternative.me/fng/
Returns 0-100 score:
  0-24:  Extreme Fear  → BLOCK all crypto LONGs
  25-39: Fear          → BLOCK crypto LONGs (tighten)
  40-60: Neutral       → Allow normal trading
  61-74: Greed         → Allow, maybe boost
  75-100: Extreme Greed → Allow, but watch for reversal
"""
import json
import time
import httpx
import os
import structlog

logger = structlog.get_logger()

API_URL = "https://api.alternative.me/fng/"

# Cache: update every 30 minutes (index updates daily but we check often)
_cache: dict[str, tuple[any, float]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get(f"bahamut:fng:{key}")
        if raw:
            data = json.loads(raw)
            _cache[key] = (data, time.time() + _CACHE_TTL)
            return data
    except Exception:
        pass
    return None


def _cache_set(key: str, data):
    _cache[key] = (data, time.time() + _CACHE_TTL)
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.setex(f"bahamut:fng:{key}", _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass


def get_fear_greed() -> dict:
    """Get current Fear & Greed Index.

    Returns:
        value: 0-100 integer
        classification: "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed"
        timestamp: when the data was updated
        should_block_longs: bool — True if value <= 39 (Fear or Extreme Fear)
    """
    cached = _cache_get("current")
    if cached:
        return cached

    try:
        r = httpx.get(API_URL, params={"limit": 1}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            entries = data.get("data", [])
            if entries:
                entry = entries[0]
                value = int(entry.get("value", 50))
                classification = entry.get("value_classification", "Neutral")
                timestamp = entry.get("timestamp", "")

                result = {
                    "value": value,
                    "classification": classification,
                    "timestamp": timestamp,
                    "should_block_longs": value <= 39,
                    "source": "alternative.me",
                }
                _cache_set("current", result)
                logger.info("fear_greed_fetched", value=value,
                            classification=classification)
                return result
    except Exception as e:
        logger.warning("fear_greed_fetch_failed", error=str(e)[:100])

    # Fallback: neutral (don't block)
    return {
        "value": 50,
        "classification": "Neutral",
        "timestamp": "",
        "should_block_longs": False,
        "source": "fallback",
    }


def get_fear_greed_history(days: int = 30) -> list[dict]:
    """Get Fear & Greed history for trend analysis."""
    cached = _cache_get(f"history_{days}")
    if cached:
        return cached

    try:
        r = httpx.get(API_URL, params={"limit": days}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            entries = data.get("data", [])
            result = [
                {
                    "value": int(e.get("value", 50)),
                    "classification": e.get("value_classification", ""),
                    "timestamp": e.get("timestamp", ""),
                }
                for e in entries
            ]
            _cache_set(f"history_{days}", result)
            return result
    except Exception:
        pass
    return []
