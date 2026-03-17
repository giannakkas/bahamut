"""
News & Economic Calendar via Finnhub.io
Free tier: 60 calls/min, real-time news (no delay), economic calendar.
https://finnhub.io/docs/api
"""
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

FINNHUB_URL = "https://finnhub.io/api/v1"


class EconomicCalendarAdapter:
    """Real economic calendar from Finnhub."""

    async def get_upcoming_events(self, days_ahead: int = 7) -> list[dict]:
        key = settings.finnhub_key
        if not key:
            return []

        start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_URL}/calendar/economic", params={
                    "from": start, "to": end, "token": key,
                })
                resp.raise_for_status()
                data = resp.json()

            events = []
            for ev in data.get("economicCalendar", [])[:40]:
                impact = self._classify_impact(ev)
                events.append({
                    "time": ev.get("time", ""),
                    "date": ev.get("date", ""),
                    "event": ev.get("event", "Unknown"),
                    "country": ev.get("country", ""),
                    "currency": self._country_to_currency(ev.get("country", "")),
                    "impact": ev.get("impact", impact),
                    "actual": ev.get("actual"),
                    "estimate": ev.get("estimate"),
                    "prev": ev.get("prev"),
                    "unit": ev.get("unit", ""),
                    "source": "finnhub",
                })

            logger.info("econ_calendar_fetched", count=len(events))
            return events

        except Exception as e:
            logger.error("econ_calendar_error", error=str(e))
            return []

    def _classify_impact(self, ev: dict) -> str:
        title = ev.get("event", "").upper()
        high = ["INTEREST RATE", "NFP", "NON-FARM", "CPI", "GDP", "FOMC",
                "ECB", "BOE", "BOJ", "EMPLOYMENT", "RETAIL SALES", "PMI",
                "PAYROLL", "FED", "INFLATION"]
        medium = ["CONSUMER", "HOUSING", "TRADE BALANCE", "INDUSTRIAL",
                  "UNEMPLOYMENT", "PPI", "CONFIDENCE", "MANUFACTURING", "SERVICES"]
        for kw in high:
            if kw in title:
                return "high"
        for kw in medium:
            if kw in title:
                return "medium"
        return "low"

    def _country_to_currency(self, country: str) -> str:
        mapping = {"US": "USD", "EU": "EUR", "GB": "GBP", "JP": "JPY",
                   "AU": "AUD", "CA": "CAD", "CH": "CHF", "CN": "CNY",
                   "DE": "EUR", "FR": "EUR", "IT": "EUR", "NZ": "NZD"}
        return mapping.get(country, country)


class NewsAdapter:
    """Real-time market news from Finnhub (NO delay on free tier)."""

    async def get_headlines(self, category: str = "general", count: int = 15) -> list[dict]:
        key = settings.finnhub_key
        if not key:
            # Fallback to NewsAPI if available
            if settings.newsapi_key:
                return await self._from_newsapi(category, count)
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_URL}/news", params={
                    "category": category, "token": key,
                })
                resp.raise_for_status()
                articles_raw = resp.json()

            articles = []
            for a in articles_raw[:count]:
                articles.append({
                    "title": a.get("headline", ""),
                    "description": a.get("summary", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "published": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else "",
                    "image": a.get("image", ""),
                    "category": a.get("category", category),
                    "related": a.get("related", ""),
                })

            logger.info("finnhub_news_fetched", category=category, count=len(articles))
            return articles

        except Exception as e:
            logger.error("finnhub_news_error", error=str(e))
            return []

    async def get_asset_news(self, symbol: str, count: int = 5) -> list[dict]:
        """Get company-specific news (stocks) or general market news (FX/crypto)."""
        key = settings.finnhub_key
        if not key:
            if settings.newsapi_key:
                return await self._newsapi_asset(symbol, count)
            return []

        # For stocks, use company news endpoint
        stock_symbols = ["AAPL", "TSLA", "NVDA", "META", "MSFT", "AMZN", "GOOGL"]
        if symbol in stock_symbols:
            return await self._company_news(symbol, count)

        # For FX/crypto/commodities, use general news with keyword filter
        category_map = {
            "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex",
            "XAUUSD": "general", "BTCUSD": "crypto", "ETHUSD": "crypto",
        }
        category = category_map.get(symbol, "general")
        articles = await self.get_headlines(category, count * 3)

        # Filter for relevance
        keywords = {
            "EURUSD": ["eur", "euro", "ecb", "dollar"],
            "GBPUSD": ["gbp", "pound", "sterling", "boe", "bank of england"],
            "USDJPY": ["jpy", "yen", "boj", "japan"],
            "XAUUSD": ["gold", "precious", "bullion"],
            "BTCUSD": ["bitcoin", "btc", "crypto"],
            "ETHUSD": ["ethereum", "eth", "crypto"],
        }
        kws = keywords.get(symbol, [symbol.lower()])
        filtered = [a for a in articles if any(kw in (a["title"] + a["description"]).lower() for kw in kws)]

        return filtered[:count] if filtered else articles[:count]

    async def _company_news(self, symbol: str, count: int) -> list[dict]:
        """Finnhub company news - real-time, no delay."""
        key = settings.finnhub_key
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_URL}/company-news", params={
                    "symbol": symbol, "from": start, "to": end, "token": key,
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
                    "category": "company",
                    "related": symbol,
                })
            logger.info("company_news_fetched", symbol=symbol, count=len(articles))
            return articles
        except Exception as e:
            logger.error("company_news_error", symbol=symbol, error=str(e))
            return []

    async def _from_newsapi(self, category: str, count: int) -> list[dict]:
        """Fallback to NewsAPI (24h delayed on free tier)."""
        query_map = {
            "general": "financial markets trading",
            "forex": "forex currency exchange rate",
            "crypto": "cryptocurrency bitcoin ethereum",
        }
        query = query_map.get(category, "financial markets")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://newsapi.org/v2/everything", params={
                    "q": query, "language": "en", "sortBy": "publishedAt",
                    "pageSize": count, "apiKey": settings.newsapi_key,
                })
                resp.raise_for_status()
                data = resp.json()
            return [{
                "title": a.get("title", ""), "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""), "url": a.get("url", ""),
                "published": a.get("publishedAt", ""), "delayed": True,
            } for a in data.get("articles", [])]
        except:
            return []

    async def _newsapi_asset(self, symbol: str, count: int) -> list[dict]:
        query_map = {
            "EURUSD": "EUR USD forex", "GBPUSD": "GBP USD forex",
            "USDJPY": "USD JPY forex", "XAUUSD": "gold price",
            "BTCUSD": "bitcoin BTC", "ETHUSD": "ethereum ETH",
            "AAPL": "Apple AAPL", "TSLA": "Tesla TSLA",
            "NVDA": "Nvidia NVDA", "META": "Meta META",
        }
        return await self._from_newsapi(query_map.get(symbol, symbol), count)


econ_calendar = EconomicCalendarAdapter()
news_adapter = NewsAdapter()
