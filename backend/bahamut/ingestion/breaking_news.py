"""
Breaking News Detector
Monitors news feeds every 2 minutes. When high-impact news hits an asset,
triggers an emergency signal cycle immediately instead of waiting for the
15-minute schedule.
"""
import json
import hashlib
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Track already-seen headlines to avoid duplicate triggers
_seen_headlines: set[str] = set()
_last_check: datetime = datetime.now(timezone.utc)

# Keywords that indicate market-moving news per asset
IMPACT_KEYWORDS = {
    "EURUSD": ["ecb", "european central bank", "eurozone", "euro area gdp",
               "fed", "federal reserve", "fomc", "interest rate", "inflation",
               "tariff", "trade war", "sanctions"],
    "GBPUSD": ["bank of england", "boe", "uk gdp", "uk inflation", "brexit",
               "sterling", "gilt", "uk economy"],
    "USDJPY": ["bank of japan", "boj", "yen", "japan gdp", "yield curve control",
               "us treasury", "us bonds"],
    "XAUUSD": ["gold", "bullion", "safe haven", "geopolitical", "war",
               "middle east", "nuclear", "sanctions", "fed rate"],
    "BTCUSD": ["bitcoin", "btc", "crypto regulation", "sec crypto", "bitcoin etf",
               "crypto ban", "stablecoin", "tether"],
    "ETHUSD": ["ethereum", "eth", "defi", "crypto regulation", "sec crypto",
               "ethereum etf"],
    "AAPL":   ["apple", "iphone", "app store", "tim cook", "apple earnings",
               "apple china"],
    "TSLA":   ["tesla", "elon musk", "ev", "electric vehicle", "tesla delivery",
               "tesla recall", "autopilot"],
    "NVDA":   ["nvidia", "gpu", "ai chips", "data center", "nvidia earnings",
               "semiconductor", "chip export"],
    "META":   ["meta", "facebook", "instagram", "threads", "zuckerberg",
               "social media regulation", "meta earnings"],
}

# High urgency phrases that always trigger regardless of asset
EMERGENCY_PHRASES = [
    "breaking:", "just in:", "flash:", "urgent:",
    "rate decision", "rate cut", "rate hike", "emergency meeting",
    "war", "invasion", "missile", "nuclear",
    "crash", "circuit breaker", "flash crash", "black swan",
    "default", "bankruptcy", "bank run", "lehman",
    "pandemic", "lockdown",
]


async def check_breaking_news() -> list[dict]:
    """
    Check for breaking news that could impact monitored assets.
    Returns list of alerts with affected assets and urgency.
    """
    global _seen_headlines, _last_check

    key = settings.finnhub_key
    if not key:
        return []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://finnhub.io/api/v1/news", params={
                "category": "general", "token": key,
            })
            resp.raise_for_status()
            articles = resp.json()

        alerts = []
        now = datetime.now(timezone.utc)

        for article in articles[:20]:
            headline = article.get("headline", "")
            pub_time = article.get("datetime", 0)
            source = article.get("source", "")

            if not headline:
                continue

            # Skip if already seen
            h_hash = hashlib.md5(headline.encode()).hexdigest()
            if h_hash in _seen_headlines:
                continue

            # Skip if older than 30 minutes
            if pub_time:
                pub_dt = datetime.fromtimestamp(pub_time, tz=timezone.utc)
                if (now - pub_dt).total_seconds() > 1800:
                    continue

            # Check for emergency phrases
            headline_lower = headline.lower()
            is_emergency = any(phrase in headline_lower for phrase in EMERGENCY_PHRASES)

            # Check which assets are affected
            affected_assets = []
            for asset, keywords in IMPACT_KEYWORDS.items():
                if any(kw in headline_lower for kw in keywords):
                    affected_assets.append(asset)

            # If emergency phrase but no specific asset, affect all major ones
            if is_emergency and not affected_assets:
                affected_assets = ["EURUSD", "XAUUSD", "BTCUSD"]

            if affected_assets or is_emergency:
                # Score the impact using Gemini if available
                impact_score = await _score_impact(headline, source, affected_assets)

                if impact_score >= 0.6 or is_emergency:
                    alert = {
                        "headline": headline,
                        "source": source,
                        "published": datetime.fromtimestamp(pub_time, tz=timezone.utc).isoformat() if pub_time else "",
                        "affected_assets": affected_assets,
                        "impact_score": impact_score,
                        "is_emergency": is_emergency,
                        "url": article.get("url", ""),
                    }
                    alerts.append(alert)
                    _seen_headlines.add(h_hash)

                    logger.warning("breaking_news_detected",
                                   headline=headline[:100], source=source,
                                   assets=affected_assets, score=impact_score,
                                   emergency=is_emergency)

        # Trim seen headlines cache (keep last 500)
        if len(_seen_headlines) > 500:
            _seen_headlines = set(list(_seen_headlines)[-300:])

        _last_check = now
        return alerts

    except Exception as e:
        logger.error("breaking_news_check_failed", error=str(e))
        return []


async def _score_impact(headline: str, source: str, assets: list[str]) -> float:
    """Use Gemini to score how impactful a headline is for trading (0-1)."""

    # Quick heuristic first
    headline_lower = headline.lower()
    base_score = 0.5

    # Source credibility boost
    premium_sources = ["reuters", "bloomberg", "cnbc", "financial times", "wsj",
                       "wall street journal", "associated press", "ap"]
    if any(s in source.lower() for s in premium_sources):
        base_score += 0.1

    # Emergency phrase boost
    if any(p in headline_lower for p in EMERGENCY_PHRASES):
        base_score += 0.2

    # Numbers in headline (specific data = more impactful)
    if any(c.isdigit() for c in headline) and ("%" in headline or "$" in headline or "billion" in headline_lower):
        base_score += 0.1

    # Try Gemini for precise scoring
    if settings.gemini_api_key:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                    json={
                        "contents": [{"parts": [{"text":
                            f"Rate this headline's market impact from 0.0 to 1.0 for trading {', '.join(assets)}.\n"
                            f"Headline: {headline}\nSource: {source}\n"
                            f"Respond with ONLY a number between 0.0 and 1.0."}]}],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": 10},
                    },
                )
                if resp.status_code == 200:
                    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    # Extract number
                    for token in text.split():
                        try:
                            score = float(token)
                            if 0 <= score <= 1:
                                return score
                        except ValueError:
                            continue
        except Exception as e:
            logger.warning("breaking_news_llm_scoring_failed", error=str(e))

    return min(1.0, base_score)
