"""
Bahamut v3 — Multi-Asset Data Fetcher

Fetches synchronized price series for cross-asset intelligence.
Caches aggressively to stay within API rate limits.
"""
import asyncio
import time as _time
import structlog
from typing import Optional

logger = structlog.get_logger()

# Cross-asset context assets — always fetched
CONTEXT_ASSETS = ["SPX", "IXIC", "BTCUSD", "ETHUSD", "XAUUSD", "EURUSD", "USDJPY", "GBPUSD"]

# Cache: {asset: ([closes], timestamp)}
_price_cache: dict[str, tuple[list[float], float]] = {}
_CACHE_TTL = 600  # 10 min (cross-asset context doesn't need to be real-time)


async def fetch_context_prices(
    target_asset: str,
    timeframe: str = "4H",
    count: int = 120,
) -> dict[str, list[float]]:
    """
    Fetch close prices for context assets + the target asset.
    Returns: {"BTCUSD": [p1, p2, ...], "SPX": [...], ...}
    All series have `count` data points (or fewer if unavailable).
    """
    assets_to_fetch = set(CONTEXT_ASSETS)
    assets_to_fetch.add(target_asset)

    now = _time.time()
    result = {}
    needs_fetch = []

    # Check cache first
    for asset in assets_to_fetch:
        cached = _price_cache.get(asset)
        if cached and (now - cached[1]) < _CACHE_TTL and len(cached[0]) >= 20:
            result[asset] = cached[0]
        else:
            needs_fetch.append(asset)

    if not needs_fetch:
        return result

    # Fetch missing assets
    try:
        from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol, to_twelve_interval

        if not twelve_data.configured:
            logger.warning("twelvedata_not_configured_for_cross_asset")
            return result

        td_interval = to_twelve_interval(timeframe)

        # Fetch in batches to respect rate limits
        batch_size = 4  # Twelve Data allows batch requests
        for i in range(0, len(needs_fetch), batch_size):
            batch = needs_fetch[i:i + batch_size]
            tasks = []
            for asset in batch:
                tasks.append(_fetch_single(asset, td_interval, count))

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for asset, res in zip(batch, batch_results):
                if isinstance(res, list) and len(res) >= 10:
                    result[asset] = res
                    _price_cache[asset] = (res, now)
                elif isinstance(res, Exception):
                    logger.debug("cross_asset_fetch_failed", asset=asset, error=str(res)[:60])

            # Small delay between batches
            if i + batch_size < len(needs_fetch):
                await asyncio.sleep(0.5)

    except Exception as e:
        logger.error("multi_asset_fetch_failed", error=str(e))

    logger.info("cross_asset_data_ready", fetched=len(result),
                needed=len(needs_fetch), cached=len(assets_to_fetch) - len(needs_fetch))
    return result


async def _fetch_single(asset: str, interval: str, count: int) -> list[float]:
    """Fetch close prices for a single asset."""
    from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol

    td_symbol = to_twelve_symbol(asset)
    candles = await twelve_data.get_candles(td_symbol, interval, count=count)

    if not candles:
        return []

    return [c["close"] for c in candles]


def get_cached_prices() -> dict[str, list[float]]:
    """Return whatever is in cache (for use in backtesting without API calls)."""
    now = _time.time()
    return {
        asset: prices for asset, (prices, ts) in _price_cache.items()
        if now - ts < _CACHE_TTL * 3  # Slightly stale is OK for backtesting
    }


def inject_prices(asset: str, prices: list[float]):
    """Inject prices into cache (used by backtester)."""
    _price_cache[asset] = (prices, _time.time())
