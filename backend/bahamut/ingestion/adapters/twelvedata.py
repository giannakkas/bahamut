"""
Twelve Data Market Data Adapter
Free tier: 800 API calls/day. Covers FX, stocks, crypto, commodities.
"""
import httpx
import structlog
from typing import Optional
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

BASE_URL = "https://api.twelvedata.com"


class TwelveDataAdapter:
    def __init__(self):
        self.api_key = settings.twelve_data_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def get_candles(self, symbol: str, interval: str = "4h", count: int = 200) -> list[dict]:
        if not self.configured:
            return []

        url = f"{BASE_URL}/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": count, "apikey": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            if "code" in data and data["code"] != 200:
                logger.error("twelvedata_error", code=data.get("code"), message=data.get("message", ""))
                return []

            values = data.get("values", [])
            if not values:
                return []

            candles = []
            for v in reversed(values):
                candles.append({
                    "time": v["datetime"],
                    "open": float(v["open"]),
                    "high": float(v["high"]),
                    "low": float(v["low"]),
                    "close": float(v["close"]),
                    "volume": int(float(v.get("volume", 0))),
                    "complete": True,
                })

            logger.info("twelvedata_candles", symbol=symbol, interval=interval, count=len(candles))
            return candles

        except Exception as e:
            logger.error("twelvedata_fetch_error", symbol=symbol, error=str(e))
            return []

    async def get_latest_price(self, symbol: str) -> Optional[dict]:
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{BASE_URL}/price", params={"symbol": symbol, "apikey": self.api_key})
                resp.raise_for_status()
                data = resp.json()
            if "price" not in data:
                return None
            price = float(data["price"])
            return {"instrument": symbol, "mid": price, "bid": price * 0.99995, "ask": price * 1.00005, "tradeable": True}
        except Exception as e:
            logger.error("twelvedata_price_error", symbol=symbol, error=str(e))
            return None

    async def health_check(self) -> dict:
        if not self.configured:
            return {"healthy": False, "reason": "TWELVE_DATA_KEY not configured"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{BASE_URL}/api_usage", params={"apikey": self.api_key})
                resp.raise_for_status()
                data = resp.json()
            return {"healthy": True, "daily_usage": data.get("current_usage", 0), "daily_limit": data.get("plan_limit", 800)}
        except Exception as e:
            return {"healthy": False, "reason": str(e)}


# ── Symbol Maps ──
# Twelve Data uses standard ticker format
TWELVE_SYMBOL_MAP = {
    # FX
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD",
    "USDCHF": "USD/CHF",
    "USDCAD": "USD/CAD",
    # Commodities
    "XAUUSD": "XAU/USD",
    "XAGUSD": "XAG/USD",
    # Crypto (Twelve Data uses /USD format)
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "SOLUSD": "SOL/USD",
    # US Stocks (Twelve Data uses plain tickers)
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "NVDA": "NVDA",
    "META": "META",
    "MSFT": "MSFT",
    "AMZN": "AMZN",
    "GOOGL": "GOOGL",
    # Indices
    "SPX": "SPX",
    "IXIC": "IXIC",
}

TWELVE_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1H": "1h", "4H": "4h", "1D": "1day", "1W": "1week",
}


def to_twelve_symbol(symbol: str) -> str:
    return TWELVE_SYMBOL_MAP.get(symbol, symbol)


def to_twelve_interval(tf: str) -> str:
    return TWELVE_INTERVAL_MAP.get(tf, tf)


twelve_data = TwelveDataAdapter()
