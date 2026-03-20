"""
Historical data loader for backtesting.
Fetches candle data from Twelve Data or loads from CSV.
"""
import json
import os
from datetime import datetime, timedelta
import structlog
import httpx

logger = structlog.get_logger()


async def fetch_historical_candles(
    symbol: str,
    interval: str = "4h",
    days: int = 90,
    api_key: str = "",
) -> list[dict]:
    """
    Fetch historical candles from Twelve Data API.
    Returns list of dicts: {datetime, open, high, low, close, volume}
    """
    if not api_key:
        api_key = os.environ.get("TWELVE_DATA_KEY", "")
    if not api_key:
        raise ValueError("TWELVE_DATA_KEY required for historical data")

    # Map symbols
    symbol_map = {
        "BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD", "SOLUSD": "SOL/USD",
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "XAUUSD": "XAU/USD", "XAGUSD": "XAG/USD",
    }
    td_symbol = symbol_map.get(symbol, symbol)

    # Twelve Data max is 5000 candles per request
    # 4h candles: ~6 per day, 90 days = 540
    count = min(5000, days * 6 if interval == "4h" else days * 24 if interval == "1h" else days)

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": td_symbol,
        "interval": interval,
        "outputsize": count,
        "apikey": api_key,
        "format": "JSON",
        "order": "ASC",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if "values" not in data:
        raise ValueError(f"No data returned: {data.get('message', 'unknown error')}")

    candles = []
    for v in data["values"]:
        candles.append({
            "datetime": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
            "volume": float(v.get("volume", 0)),
        })

    logger.info("historical_data_loaded", symbol=symbol, interval=interval,
                candles=len(candles), days=days)
    return candles


def load_candles_from_csv(filepath: str) -> list[dict]:
    """Load candles from CSV: datetime,open,high,low,close,volume"""
    import csv
    candles = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "datetime": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })
    return candles


def generate_synthetic_candles(
    base_price: float = 1.0850,
    count: int = 500,
    volatility: float = 0.001,
    trend: float = 0.0,  # Zero drift for fair testing (was 0.00005)
) -> list[dict]:
    """Generate synthetic candle data for testing without API access."""
    import numpy as np
    np.random.seed(42)

    candles = []
    price = base_price

    for i in range(count):
        returns = np.random.normal(trend, volatility)
        o = price
        c = price * (1 + returns)
        h = max(o, c) * (1 + abs(np.random.normal(0, volatility * 0.5)))
        l = min(o, c) * (1 - abs(np.random.normal(0, volatility * 0.5)))
        vol = max(100, np.random.normal(10000, 3000))

        candles.append({
            "datetime": f"2025-01-01 {i:05d}",
            "open": round(o, 6),
            "high": round(h, 6),
            "low": round(l, 6),
            "close": round(c, 6),
            "volume": round(vol, 0),
        })
        price = c

    return candles
