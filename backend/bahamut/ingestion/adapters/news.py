"""
News & Economic Calendar
- Finnhub: real-time news (free, no delay)
- Forex Factory: economic calendar (free JSON feed)
- NewsAPI: fallback (24h delay)
"""
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

FINNHUB_URL = "https://finnhub.io/api/v1"


class EconomicCalendarAdapter:
    """Free economic calendar from multiple sources."""

    async def get_upcoming_events(self, days_ahead: int = 7) -> list[dict]:
        # Try Finnhub economic calendar first (most reliable, key already works)
        events = await self._from_finnhub()
        if events:
            return events

        # Fallback to Forex Factory free JSON feed
        events = await self._from_forex_factory()
        if events:
            return events

        # Last resort: Twelve Data earnings
        events = await self._from_twelvedata_earnings()
        if events:
            return events

        return []

    async def _from_finnhub(self) -> list[dict]:
        """Finnhub economic calendar — uses existing FINNHUB_KEY."""
        key = settings.finnhub_key
        if not key:
            return []
        try:
            from datetime import datetime, timezone, timedelta
            start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://finnhub.io/api/v1/calendar/economic", params={
                    "from": start, "to": end, "token": key,
                })
                resp.raise_for_status()
                data = resp.json()

            raw_events = data.get("economicCalendar", data.get("result", []))
            if not raw_events:
                logger.warning("finnhub_calendar_empty", keys=list(data.keys()))
                return []

            events = []
            for ev in raw_events:
                impact_raw = ev.get("impact", "low")
                impact = impact_raw if impact_raw in ("high", "medium", "low") else "low"

                events.append({
                    "time": ev.get("time", ""),
                    "date": ev.get("date", ev.get("time", "")[:10] if ev.get("time") else ""),
                    "event": ev.get("event", "Unknown"),
                    "country": ev.get("country", ""),
                    "currency": ev.get("country", ""),
                    "impact": impact,
                    "actual": ev.get("actual") if ev.get("actual") is not None else None,
                    "estimate": ev.get("estimate") if ev.get("estimate") is not None else None,
                    "prev": ev.get("prev") if ev.get("prev") is not None else None,
                    "unit": ev.get("unit", ""),
                    "source": "finnhub",
                })

            logger.info("finnhub_calendar_fetched", count=len(events))
            return events

        except Exception as e:
            logger.error("finnhub_calendar_error", error=str(e))
            return []

    async def _from_forex_factory(self) -> list[dict]:
        """Forex Factory publishes a free JSON calendar feed."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
                resp.raise_for_status()
                data = resp.json()

            events = []
            for ev in data:
                impact = ev.get("impact", "Low")
                if impact == "Holiday":
                    continue

                impact_normalized = "high" if impact == "High" else "medium" if impact == "Medium" else "low"

                events.append({
                    "time": ev.get("time", ""),
                    "date": ev.get("date", ""),
                    "event": ev.get("title", "Unknown"),
                    "country": ev.get("country", ""),
                    "currency": ev.get("country", ""),  # FF uses currency codes as country
                    "impact": impact_normalized,
                    "actual": ev.get("actual") if ev.get("actual") else None,
                    "estimate": ev.get("forecast") if ev.get("forecast") else None,
                    "prev": ev.get("previous") if ev.get("previous") else None,
                    "unit": "",
                    "source": "forexfactory",
                })

            logger.info("forexfactory_calendar_fetched", count=len(events))
            return events

        except Exception as e:
            logger.error("forexfactory_error", error=str(e))
            return []

    async def _from_twelvedata_earnings(self) -> list[dict]:
        """Twelve Data earnings calendar (free tier)."""
        if not settings.twelve_data_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://api.twelvedata.com/earnings_calendar", params={
                    "apikey": settings.twelve_data_key,
                })
                if resp.status_code != 200:
                    return []
                data = resp.json()

            events = []
            for ev in data.get("earnings", data.get("data", []))[:20]:
                events.append({
                    "time": "",
                    "date": ev.get("date", ""),
                    "event": f"{ev.get('symbol', '')} Earnings ({ev.get('period', '')})",
                    "country": "US",
                    "currency": "USD",
                    "impact": "medium",
                    "actual": ev.get("actual"),
                    "estimate": ev.get("estimate"),
                    "prev": None,
                    "unit": "",
                    "source": "twelvedata",
                })
            return events
        except Exception as e:
            logger.error("twelvedata_earnings_error", error=str(e))
            return []


class NewsAdapter:
    """Real-time market news from Finnhub (NO delay)."""

    async def get_headlines(self, category: str = "general", count: int = 15) -> list[dict]:
        key = settings.finnhub_key
        if key:
            articles = await self._from_finnhub(category, count)
            if articles:
                return articles

        if settings.newsapi_key:
            return await self._from_newsapi(category, count)

        return []

    async def _from_finnhub(self, category: str, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_URL}/news", params={
                    "category": category, "token": settings.finnhub_key,
                })
                resp.raise_for_status()
                data = resp.json()

            articles = []
            for a in data[:count]:
                articles.append({
                    "title": a.get("headline", ""),
                    "description": a.get("summary", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "published": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else "",
                    "image": a.get("image", ""),
                    "category": a.get("category", category),
                })
            logger.info("finnhub_news", category=category, count=len(articles))
            return articles
        except Exception as e:
            logger.error("finnhub_news_error", error=str(e))
            return []

    async def get_asset_news(self, symbol: str, count: int = 5) -> list[dict]:
        key = settings.finnhub_key
        if not key:
            if settings.newsapi_key:
                return await self._newsapi_asset(symbol, count)
            return []

        stocks = ["AAPL", "TSLA", "NVDA", "META", "MSFT", "AMZN", "GOOGL"]
        if symbol in stocks:
            return await self._company_news(symbol, count)

        category_map = {
            "EURUSD": "general", "GBPUSD": "general", "USDJPY": "general",
            "XAUUSD": "general", "BTCUSD": "crypto", "ETHUSD": "crypto",
        }
        category = category_map.get(symbol, "general")
        articles = await self.get_headlines(category, count * 3)

        keywords = {
            "EURUSD": ["eur", "euro", "ecb", "dollar"],
            "GBPUSD": ["gbp", "pound", "sterling", "boe"],
            "USDJPY": ["jpy", "yen", "boj", "japan"],
            "XAUUSD": ["gold", "precious", "bullion"],
            "BTCUSD": ["bitcoin", "btc"],
            "ETHUSD": ["ethereum", "eth"],
        }
        kws = keywords.get(symbol, [symbol.lower()])
        filtered = [a for a in articles if any(kw in (a.get("title", "") + a.get("description", "")).lower() for kw in kws)]
        return filtered[:count] if filtered else articles[:count]

    async def _company_news(self, symbol: str, count: int) -> list[dict]:
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_URL}/company-news", params={
                    "symbol": symbol, "from": start, "to": end, "token": settings.finnhub_key,
                })
                resp.raise_for_status()
                data = resp.json()
            return [{
                "title": a.get("headline", ""), "description": a.get("summary", ""),
                "source": a.get("source", ""), "url": a.get("url", ""),
                "published": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else "",
                "image": a.get("image", ""),
            } for a in data[:count]]
        except Exception as e:
            logger.error("company_news_error", symbol=symbol, error=str(e))
            return []

    async def _from_newsapi(self, category: str, count: int) -> list[dict]:
        query_map = {"general": "financial markets", "forex": "forex currency", "crypto": "cryptocurrency bitcoin"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://newsapi.org/v2/everything", params={
                    "q": query_map.get(category, "markets"), "language": "en",
                    "sortBy": "publishedAt", "pageSize": count, "apiKey": settings.newsapi_key,
                })
                resp.raise_for_status()
                data = resp.json()
            return [{
                "title": a.get("title", ""), "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""), "url": a.get("url", ""),
                "published": a.get("publishedAt", ""), "delayed": True,
            } for a in data.get("articles", [])]
        except Exception as e:
            logger.warning("newsapi_category_failed", category=category, error=str(e))
            return []

    async def _newsapi_asset(self, symbol: str, count: int) -> list[dict]:
        qm = {"EURUSD": "EUR USD forex", "BTCUSD": "bitcoin", "AAPL": "Apple AAPL", "TSLA": "Tesla TSLA", "NVDA": "Nvidia NVDA", "META": "Meta META"}
        return await self._from_newsapi(qm.get(symbol, symbol), count)


econ_calendar = EconomicCalendarAdapter()
news_adapter = NewsAdapter()
