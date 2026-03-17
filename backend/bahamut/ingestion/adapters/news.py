"""
News & Economic Calendar Data Adapters
- Twelve Data: economic calendar (free, already have key)
- NewsAPI.org: financial headlines (free 100 req/day)
- Fallback: Claude API analysis
"""
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from typing import Optional
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class EconomicCalendarAdapter:
    """Fetch real economic events from Twelve Data."""

    async def get_upcoming_events(self, days_ahead: int = 7) -> list[dict]:
        if not settings.twelve_data_key:
            return []

        start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        url = "https://api.twelvedata.com/earnings_calendar"  # Free endpoint
        # Twelve Data doesn't have a full econ calendar on free tier
        # Use their earnings calendar for stocks + manual forex events

        # Try the economic calendar (may require paid plan)
        econ_url = "https://api.twelvedata.com/economic_calendar"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(econ_url, params={
                    "start_date": start, "end_date": end,
                    "apikey": settings.twelve_data_key,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    events = []
                    for ev in data.get("events", data.get("data", []))[:30]:
                        events.append({
                            "time": ev.get("date", ev.get("datetime", "")),
                            "event": ev.get("event", ev.get("title", "Unknown")),
                            "country": ev.get("country", ""),
                            "currency": ev.get("currency", ""),
                            "impact": self._classify_impact(ev),
                            "actual": ev.get("actual"),
                            "forecast": ev.get("forecast", ev.get("estimate")),
                            "previous": ev.get("previous"),
                            "source": "twelvedata",
                        })
                    if events:
                        logger.info("econ_calendar_fetched", count=len(events))
                        return events
        except Exception as e:
            logger.warning("econ_calendar_error", error=str(e))

        return []

    def _classify_impact(self, event: dict) -> str:
        title = (event.get("event", "") + event.get("title", "")).upper()
        high_keywords = ["INTEREST RATE", "NFP", "NON-FARM", "CPI", "GDP", "FOMC",
                         "ECB", "BOE", "BOJ", "EMPLOYMENT", "RETAIL SALES", "PMI"]
        medium_keywords = ["CONSUMER", "HOUSING", "TRADE BALANCE", "INDUSTRIAL",
                           "UNEMPLOYMENT", "PPI", "CONFIDENCE"]

        for kw in high_keywords:
            if kw in title:
                return "HIGH"
        for kw in medium_keywords:
            if kw in title:
                return "MEDIUM"
        return "LOW"


class NewsAdapter:
    """Fetch financial news headlines."""

    async def get_headlines(self, query: str = "forex trading market", count: int = 10) -> list[dict]:
        """Get financial news from free sources."""
        headlines = []

        # Try NewsAPI if key configured
        if settings.newsapi_key:
            headlines = await self._from_newsapi(query, count)
            if headlines:
                return headlines

        # Try Twelve Data news
        if settings.twelve_data_key:
            headlines = await self._from_twelvedata(count)
            if headlines:
                return headlines

        return []

    async def _from_newsapi(self, query: str, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://newsapi.org/v2/everything", params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": count,
                    "apiKey": settings.newsapi_key,
                })
                resp.raise_for_status()
                data = resp.json()

            articles = []
            for a in data.get("articles", []):
                articles.append({
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "url": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "sentiment": None,  # Will be scored by Sentiment Agent
                })
            logger.info("newsapi_fetched", count=len(articles))
            return articles
        except Exception as e:
            logger.error("newsapi_error", error=str(e))
            return []

    async def _from_twelvedata(self, count: int) -> list[dict]:
        """Twelve Data doesn't have news on free tier, but try anyway."""
        return []

    async def get_asset_news(self, symbol: str, count: int = 5) -> list[dict]:
        """Get news specifically about an asset."""
        query_map = {
            "EURUSD": "EUR USD forex ECB Federal Reserve",
            "GBPUSD": "GBP USD forex Bank of England",
            "USDJPY": "USD JPY forex Bank of Japan",
            "XAUUSD": "gold price commodities",
            "BTCUSD": "bitcoin crypto BTC",
            "ETHUSD": "ethereum crypto ETH",
            "AAPL": "Apple AAPL stock",
            "TSLA": "Tesla TSLA stock",
            "NVDA": "Nvidia NVDA stock AI chips",
            "META": "Meta Facebook META stock",
        }
        query = query_map.get(symbol, symbol)
        return await self.get_headlines(query, count)


# Singletons
econ_calendar = EconomicCalendarAdapter()
news_adapter = NewsAdapter()
