"""
OANDA Market Data Adapter
Fetches live FX prices, candles, and account data from OANDA's REST API.
Supports both practice and live environments.
"""
import httpx
import structlog
from datetime import datetime, timezone
from typing import Optional

from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# OANDA API endpoints
PRACTICE_URL = "https://api-fxpractice.oanda.com"
LIVE_URL = "https://api-fxtrade.oanda.com"


class OandaAdapter:
    """Fetches market data from OANDA REST API v20."""

    def __init__(self):
        self.api_key = settings.oanda_api_key
        self.account_id = settings.oanda_account_id
        self.base_url = PRACTICE_URL  # Switch to LIVE_URL for production
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.account_id)

    async def get_candles(
        self, instrument: str, granularity: str = "H4",
        count: int = 100, price: str = "MBA"
    ) -> list[dict]:
        """
        Fetch OHLCV candles.
        instrument: e.g. "EUR_USD", "XAU_USD"
        granularity: S5,M1,M5,M15,M30,H1,H4,D,W,M
        price: M=mid, B=bid, A=ask, MBA=all
        """
        if not self.configured:
            logger.warning("oanda_not_configured")
            return []

        url = f"{self.base_url}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": granularity,
            "count": count,
            "price": price,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()

            candles = []
            for c in data.get("candles", []):
                if not c.get("complete", False) and len(candles) > 0:
                    continue  # skip incomplete candle unless it's the only one

                mid = c.get("mid", {})
                candles.append({
                    "time": c["time"],
                    "open": float(mid.get("o", 0)),
                    "high": float(mid.get("h", 0)),
                    "low": float(mid.get("l", 0)),
                    "close": float(mid.get("c", 0)),
                    "volume": int(c.get("volume", 0)),
                    "complete": c.get("complete", False),
                })

            logger.info("oanda_candles_fetched", instrument=instrument,
                        granularity=granularity, count=len(candles))
            return candles

        except httpx.HTTPStatusError as e:
            logger.error("oanda_http_error", status=e.response.status_code,
                         detail=e.response.text[:200])
            return []
        except Exception as e:
            logger.error("oanda_error", error=str(e))
            return []

    async def get_latest_price(self, instrument: str) -> Optional[dict]:
        """Get current bid/ask/mid price for an instrument."""
        if not self.configured:
            return None

        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing"
        params = {"instruments": instrument}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()

            prices = data.get("prices", [])
            if not prices:
                return None

            p = prices[0]
            bid = float(p["bids"][0]["price"]) if p.get("bids") else 0
            ask = float(p["asks"][0]["price"]) if p.get("asks") else 0

            return {
                "instrument": instrument,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 6),
                "spread": round(ask - bid, 6),
                "time": p.get("time", ""),
                "tradeable": p.get("tradeable", False),
            }
        except Exception as e:
            logger.error("oanda_price_error", instrument=instrument, error=str(e))
            return None

    async def get_multiple_prices(self, instruments: list[str]) -> list[dict]:
        """Get prices for multiple instruments at once."""
        if not self.configured:
            return []

        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing"
        params = {"instruments": ",".join(instruments)}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()

            results = []
            for p in data.get("prices", []):
                bid = float(p["bids"][0]["price"]) if p.get("bids") else 0
                ask = float(p["asks"][0]["price"]) if p.get("asks") else 0
                results.append({
                    "instrument": p["instrument"],
                    "bid": bid,
                    "ask": ask,
                    "mid": round((bid + ask) / 2, 6),
                    "spread": round(ask - bid, 6),
                    "tradeable": p.get("tradeable", False),
                })
            return results
        except Exception as e:
            logger.error("oanda_multi_price_error", error=str(e))
            return []

    async def get_account_summary(self) -> Optional[dict]:
        """Get account balance, equity, margin info."""
        if not self.configured:
            return None

        url = f"{self.base_url}/v3/accounts/{self.account_id}/summary"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=self.headers)
                resp.raise_for_status()
                data = resp.json()

            acct = data.get("account", {})
            return {
                "balance": float(acct.get("balance", 0)),
                "equity": float(acct.get("NAV", 0)),
                "unrealized_pnl": float(acct.get("unrealizedPL", 0)),
                "margin_used": float(acct.get("marginUsed", 0)),
                "margin_available": float(acct.get("marginAvailable", 0)),
                "open_trade_count": int(acct.get("openTradeCount", 0)),
                "open_position_count": int(acct.get("openPositionCount", 0)),
                "currency": acct.get("currency", "USD"),
            }
        except Exception as e:
            logger.error("oanda_account_error", error=str(e))
            return None

    async def health_check(self) -> dict:
        """Check if OANDA API is reachable."""
        if not self.configured:
            return {"healthy": False, "reason": "OANDA API key or account ID not configured"}

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self.base_url}/v3/accounts/{self.account_id}",
                    headers=self.headers,
                )
                resp.raise_for_status()
            return {"healthy": True, "reason": "OK"}
        except Exception as e:
            return {"healthy": False, "reason": str(e)}


# Instrument mapping: our symbols -> OANDA format
SYMBOL_MAP = {
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "USDJPY": "USD_JPY",
    "AUDUSD": "AUD_USD",
    "USDCHF": "USD_CHF",
    "USDCAD": "USD_CAD",
    "NZDUSD": "NZD_USD",
    "XAUUSD": "XAU_USD",
    "XAGUSD": "XAG_USD",
}

GRANULARITY_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1H": "H1", "4H": "H4", "1D": "D", "1W": "W",
}


def to_oanda_instrument(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol.replace("/", "_"))


def to_oanda_granularity(tf: str) -> str:
    return GRANULARITY_MAP.get(tf, tf)


# Singleton
oanda = OandaAdapter()
