"""
Bahamut.AI — CryptoPanic Sentiment Adapter

Fetches crypto news sentiment from CryptoPanic API.
Aggressively cached to conserve API quota (100 req on free plan).

Usage:
    from bahamut.sentiment.cryptopanic import get_sentiment, get_market_mood

    sentiment = get_sentiment("BTC")
    # Returns: {"bullish": 5, "bearish": 12, "neutral": 3, "score": -0.35, "mood": "bearish"}

    mood = get_market_mood()
    # Returns: {"overall": "bearish", "score": -0.25, "assets": {...}}
"""
import os
import json
import time
import httpx
import structlog

logger = structlog.get_logger()

API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
BASE_URL = "https://cryptopanic.com/api/v1"

# ── Aggressive caching: query once per 30 min ──
_cache: dict[str, tuple[any, float]] = {}
_CACHE_TTL = 1800  # 30 minutes

# Map Bahamut symbols to CryptoPanic currency codes
SYMBOL_MAP = {
    "BTCUSD": "BTC", "ETHUSD": "ETH", "SOLUSD": "SOL",
    "BNBUSD": "BNB", "XRPUSD": "XRP", "ADAUSD": "ADA",
    "DOGEUSD": "DOGE", "AVAXUSD": "AVAX", "LINKUSD": "LINK",
    "MATICUSD": "MATIC",
}

ALL_CURRENCIES = ",".join(set(SYMBOL_MAP.values()))


def _configured() -> bool:
    return bool(API_KEY)


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    # Also try Redis
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get(f"bahamut:sentiment:{key}")
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
        r.setex(f"bahamut:sentiment:{key}", _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass


def _fetch_posts(currencies: str = "", filter_type: str = "important") -> list[dict]:
    """Fetch posts from CryptoPanic API. One API call."""
    if not _configured():
        return []

    params = {
        "auth_token": API_KEY,
        "public": "true",
    }
    if currencies:
        params["currencies"] = currencies
    if filter_type:
        params["filter"] = filter_type

    try:
        r = httpx.get(f"{BASE_URL}/posts/", params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("results", [])
        logger.warning("cryptopanic_fetch_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.warning("cryptopanic_exception", error=str(e)[:100])
    return []


def get_sentiment(asset: str) -> dict:
    """Get sentiment for a single asset.

    Returns:
        bullish: count of bullish votes
        bearish: count of bearish votes
        neutral: count of neutral posts
        score: -1.0 (max bearish) to +1.0 (max bullish)
        mood: "bullish" | "bearish" | "neutral"
        posts: number of posts analyzed
    """
    currency = SYMBOL_MAP.get(asset, asset.replace("USD", ""))

    # Check cache — all assets cached together
    all_sentiments = _cache_get("all_sentiments")
    if all_sentiments and currency in all_sentiments:
        return all_sentiments[currency]

    # Need to refresh — fetch all at once (1 API call)
    _refresh_all_sentiments()

    all_sentiments = _cache_get("all_sentiments")
    if all_sentiments and currency in all_sentiments:
        return all_sentiments[currency]

    return _neutral_sentiment()


def get_market_mood() -> dict:
    """Get overall crypto market mood.

    Returns:
        overall: "bullish" | "bearish" | "neutral" | "extreme_fear" | "extreme_greed"
        score: -1.0 to +1.0
        assets: per-asset sentiment dict
    """
    all_sentiments = _cache_get("all_sentiments")
    if not all_sentiments:
        _refresh_all_sentiments()
        all_sentiments = _cache_get("all_sentiments")

    if not all_sentiments:
        return {"overall": "neutral", "score": 0.0, "assets": {}}

    # Average across all assets
    scores = [s["score"] for s in all_sentiments.values() if isinstance(s, dict) and "score" in s]
    avg_score = sum(scores) / max(1, len(scores))

    if avg_score <= -0.5:
        overall = "extreme_fear"
    elif avg_score <= -0.15:
        overall = "bearish"
    elif avg_score >= 0.5:
        overall = "extreme_greed"
    elif avg_score >= 0.15:
        overall = "bullish"
    else:
        overall = "neutral"

    return {
        "overall": overall,
        "score": round(avg_score, 3),
        "assets": all_sentiments,
    }


def should_block_long(asset: str) -> tuple[bool, str]:
    """Check if a LONG entry should be blocked due to bearish sentiment.

    Returns (should_block, reason).
    """
    if not _configured():
        return False, "sentiment not configured"

    sentiment = get_sentiment(asset)
    mood = get_market_mood()

    # Block if asset is heavily bearish
    if sentiment["score"] <= -0.4 and sentiment["posts"] >= 3:
        return True, f"CryptoPanic: {asset} heavily bearish (score={sentiment['score']:.2f}, {sentiment['bearish']}B/{sentiment['bullish']}B)"

    # Block if overall market is in extreme fear
    if mood["overall"] == "extreme_fear":
        return True, f"CryptoPanic: market extreme fear (score={mood['score']:.2f})"

    return False, ""


def _refresh_all_sentiments():
    """Fetch all crypto sentiments in ONE API call and cache per-asset."""
    posts = _fetch_posts(currencies=ALL_CURRENCIES, filter_type="important")

    if not posts:
        # Even on failure, cache empty result to avoid hammering API
        _cache_set("all_sentiments", {})
        return

    # Count votes per currency
    per_asset: dict[str, dict] = {}

    for post in posts:
        currencies = post.get("currencies", [])
        votes = post.get("votes", {})

        bullish = votes.get("positive", 0) + votes.get("important", 0)
        bearish = votes.get("negative", 0) + votes.get("toxic", 0)

        for curr in currencies:
            code = curr.get("code", "")
            if code not in per_asset:
                per_asset[code] = {"bullish": 0, "bearish": 0, "neutral": 0, "posts": 0}
            per_asset[code]["posts"] += 1

            if bullish > bearish:
                per_asset[code]["bullish"] += 1
            elif bearish > bullish:
                per_asset[code]["bearish"] += 1
            else:
                per_asset[code]["neutral"] += 1

    # Calculate scores
    all_sentiments = {}
    for code, data in per_asset.items():
        total_voted = data["bullish"] + data["bearish"]
        if total_voted > 0:
            score = (data["bullish"] - data["bearish"]) / total_voted
        else:
            score = 0.0

        if score > 0.15:
            mood = "bullish"
        elif score < -0.15:
            mood = "bearish"
        else:
            mood = "neutral"

        all_sentiments[code] = {
            "bullish": data["bullish"],
            "bearish": data["bearish"],
            "neutral": data["neutral"],
            "posts": data["posts"],
            "score": round(score, 3),
            "mood": mood,
        }

    _cache_set("all_sentiments", all_sentiments)
    logger.info("cryptopanic_sentiment_refreshed",
                assets=len(all_sentiments), posts=len(posts),
                overall_score=round(sum(s["score"] for s in all_sentiments.values()) / max(1, len(all_sentiments)), 3))


def _neutral_sentiment() -> dict:
    return {"bullish": 0, "bearish": 0, "neutral": 0, "posts": 0, "score": 0.0, "mood": "neutral"}
