"""
Bahamut.AI — CNN Fear & Greed Index (Stock Market)

Free, no API key. The stock market equivalent of crypto Fear & Greed.
Uses CNN's public API endpoint.

0-24:  Extreme Fear  → Block stock LONGs
25-39: Fear          → Block stock LONGs
40-60: Neutral       → Allow
61-74: Greed         → Allow
75-100: Extreme Greed → Caution
"""
import json
import time
import httpx
import os
import structlog

logger = structlog.get_logger()

CNN_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_cache: dict[str, tuple[any, float]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get(f"bahamut:cnn_fng:{key}")
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
        r.setex(f"bahamut:cnn_fng:{key}", _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass


def _classify(value: int) -> str:
    if value <= 24:
        return "Extreme Fear"
    elif value <= 39:
        return "Fear"
    elif value <= 60:
        return "Neutral"
    elif value <= 74:
        return "Greed"
    else:
        return "Extreme Greed"


def get_stock_fear_greed() -> dict:
    """Get CNN Fear & Greed Index for US stock market.

    Returns:
        value: 0-100
        classification: "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed"
        should_block_longs: bool
        indicators: dict of 7 sub-indicators (if available)
    """
    cached = _cache_get("current")
    if cached:
        return cached

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Bahamut/1.0)",
            "Accept": "application/json",
        }
        r = httpx.get(CNN_API_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            fg = data.get("fear_and_greed", {})
            score = round(fg.get("score", 50))
            classification = _classify(score)

            # Extract 7 sub-indicators
            indicators = {}
            for key in ["market_momentum", "stock_price_strength", "stock_price_breadth",
                        "put_call_options", "market_volatility", "safe_haven_demand",
                        "junk_bond_demand"]:
                ind = data.get(key, {})
                if ind:
                    indicators[key] = {
                        "score": round(ind.get("score", 50)),
                        "rating": ind.get("rating", "neutral"),
                    }

            result = {
                "value": score,
                "classification": classification,
                "should_block_longs": score <= 39,
                "indicators": indicators,
                "source": "CNN Fear & Greed",
            }
            _cache_set("current", result)
            logger.info("cnn_fear_greed_fetched", value=score, classification=classification)
            return result
    except Exception as e:
        logger.warning("cnn_fear_greed_failed", error=str(e)[:100])

    # Fallback
    return {
        "value": 50,
        "classification": "Neutral",
        "should_block_longs": False,
        "indicators": {},
        "source": "fallback",
    }
