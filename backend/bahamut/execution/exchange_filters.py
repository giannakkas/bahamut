"""
Bahamut.AI — Binance Futures Exchange Filters (Phase 2 Item 6)

Replaces the hardcoded _format_qty() precision table with actual exchange
metadata from /fapi/v1/exchangeInfo. Rounds quantities and prices per
symbol's real stepSize/tickSize; validates minQty/minNotional locally so
bad orders are rejected before a network round-trip to Binance.

Cache strategy:
  1. In-memory dict, refreshed every 24h
  2. Redis mirror under bahamut:binance_exchange_filters (24h TTL)
  3. If both miss and the fetch fails, fall back to hardcoded defaults
     (marked with source='fallback') so strategies never hard-fail.

Public API:
  refresh_filters(force=False) -> dict
  get_filters(symbol: str) -> dict | None
  round_qty(symbol: str, qty: float) -> float
  round_price(symbol: str, price: float) -> float
  validate_order(symbol: str, qty: float, price: float = 0.0) -> (bool, reason)
  format_qty_canonical(asset: str, qty: float) -> (str, adjustments: dict)
"""
import os
import json
import time
import math
import httpx
import structlog
from decimal import Decimal, ROUND_DOWN

logger = structlog.get_logger()

_BASE_URL = os.environ.get("BINANCE_FUTURES_BASE_URL", "https://demo-fapi.binance.com")
_CACHE_TTL_SEC = 24 * 3600
_REDIS_KEY = "bahamut:binance_exchange_filters"

# In-memory cache: {symbol: {stepSize, tickSize, minQty, minNotional,
#                            quantity_precision, price_precision, source}}
_FILTERS: dict = {}
_FILTERS_FETCHED_AT: float = 0.0

# Hardcoded fallback — matches old _format_qty behavior for safety when
# exchangeInfo is unreachable. Explicitly marked source='fallback'.
_FALLBACK_FILTERS = {
    # Low-price coins — integer quantity
    "DOGEUSDT":  {"stepSize": 1.0,     "tickSize": 0.00001, "minQty": 1.0,    "minNotional": 5.0,  "quantity_precision": 0, "price_precision": 5, "source": "fallback"},
    "PEPEUSDT":  {"stepSize": 1.0,     "tickSize": 1e-8,    "minQty": 1.0,    "minNotional": 5.0,  "quantity_precision": 0, "price_precision": 8, "source": "fallback"},
    "SHIBUSDT":  {"stepSize": 1.0,     "tickSize": 1e-8,    "minQty": 1.0,    "minNotional": 5.0,  "quantity_precision": 0, "price_precision": 8, "source": "fallback"},
    # Mid-tier crypto — 3-decimal quantity
    "BTCUSDT":   {"stepSize": 0.001,   "tickSize": 0.1,     "minQty": 0.001,  "minNotional": 5.0,  "quantity_precision": 3, "price_precision": 1, "source": "fallback"},
    "ETHUSDT":   {"stepSize": 0.001,   "tickSize": 0.01,    "minQty": 0.001,  "minNotional": 5.0,  "quantity_precision": 3, "price_precision": 2, "source": "fallback"},
    "SOLUSDT":   {"stepSize": 0.001,   "tickSize": 0.01,    "minQty": 0.001,  "minNotional": 5.0,  "quantity_precision": 3, "price_precision": 2, "source": "fallback"},
    "BNBUSDT":   {"stepSize": 0.01,    "tickSize": 0.01,    "minQty": 0.01,   "minNotional": 5.0,  "quantity_precision": 2, "price_precision": 2, "source": "fallback"},
}
# Default fallback for unknown symbols — conservative 2-decimal
_DEFAULT_FALLBACK = {
    "stepSize": 0.01, "tickSize": 0.0001,
    "minQty": 0.01, "minNotional": 5.0,
    "quantity_precision": 2, "price_precision": 4,
    "source": "fallback_default",
}


def _get_redis():
    """Local Redis helper — keep this module self-contained."""
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if url:
            return _redis.Redis.from_url(url, decode_responses=False, socket_connect_timeout=2)
    except Exception:
        pass
    return None


def _precision_from_step(step: float) -> int:
    """How many decimal places a stepSize allows.
    0.001 → 3, 1.0 → 0, 0.5 → 1, 1e-8 → 8."""
    if step <= 0:
        return 0
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _parse_filter(symbol_info: dict) -> dict | None:
    """Extract the fields we care about from one symbol's exchangeInfo entry."""
    try:
        filters = {f["filterType"]: f for f in symbol_info.get("filters", [])}
        lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE") or {}
        price = filters.get("PRICE_FILTER") or {}
        notional = (filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {})

        step_size = float(lot.get("stepSize", 0)) or float(lot.get("minQty", 0.01))
        tick_size = float(price.get("tickSize", 0.0001))
        min_qty = float(lot.get("minQty", step_size))
        min_notional = float(notional.get("notional") or notional.get("minNotional") or 0) or 5.0

        return {
            "stepSize": step_size,
            "tickSize": tick_size,
            "minQty": min_qty,
            "minNotional": min_notional,
            "quantity_precision": _precision_from_step(step_size),
            "price_precision": _precision_from_step(tick_size),
            "source": "binance_exchange_info",
        }
    except Exception as e:
        logger.warning("exchange_filter_parse_failed",
                       symbol=symbol_info.get("symbol"), error=str(e)[:100])
        return None


def _load_from_redis() -> bool:
    """Populate _FILTERS from Redis. Returns True if loaded."""
    global _FILTERS, _FILTERS_FETCHED_AT
    r = _get_redis()
    if not r:
        return False
    try:
        raw = r.get(_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            _FILTERS = data.get("filters", {})
            _FILTERS_FETCHED_AT = float(data.get("fetched_at", 0))
            # Redis stale check — still within TTL because the Redis key has
            # its own expiry, but double-check the timestamp.
            if time.time() - _FILTERS_FETCHED_AT < _CACHE_TTL_SEC:
                return True
    except Exception as e:
        logger.debug("exchange_filters_redis_load_failed", error=str(e)[:100])
    return False


def _save_to_redis():
    """Mirror _FILTERS to Redis with 24h TTL."""
    r = _get_redis()
    if not r or not _FILTERS:
        return
    try:
        data = {"filters": _FILTERS, "fetched_at": _FILTERS_FETCHED_AT}
        r.set(_REDIS_KEY, json.dumps(data), ex=_CACHE_TTL_SEC)
    except Exception as e:
        logger.debug("exchange_filters_redis_save_failed", error=str(e)[:100])


def refresh_filters(force: bool = False) -> dict:
    """Fetch /fapi/v1/exchangeInfo, parse filters, cache.
    Returns the filter dict. Populates both in-memory and Redis caches.

    If the fetch fails and we have no prior data, falls back to the
    hardcoded table. Callers get filters with source='fallback' in that case.
    """
    global _FILTERS, _FILTERS_FETCHED_AT
    now = time.time()
    # Fresh in-memory cache?
    if not force and _FILTERS and (now - _FILTERS_FETCHED_AT < _CACHE_TTL_SEC):
        return _FILTERS

    # Try Redis first
    if not force and _load_from_redis():
        logger.info("exchange_filters_loaded_from_redis", count=len(_FILTERS))
        return _FILTERS

    # Fetch from Binance
    try:
        r = httpx.get(f"{_BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
        if r.status_code != 200:
            logger.warning("exchange_info_http_error", status=r.status_code)
            raise RuntimeError(f"HTTP {r.status_code}")
        info = r.json()
        new_filters = {}
        for sym in info.get("symbols", []):
            parsed = _parse_filter(sym)
            if parsed:
                new_filters[sym["symbol"]] = parsed
        if new_filters:
            _FILTERS = new_filters
            _FILTERS_FETCHED_AT = now
            _save_to_redis()
            logger.info("exchange_filters_refreshed", count=len(_FILTERS),
                        source="binance_exchange_info")
            return _FILTERS
    except Exception as e:
        logger.warning("exchange_filters_refresh_failed", error=str(e)[:150])

    # Fallback: use hardcoded table. Only applied if we have nothing.
    if not _FILTERS:
        _FILTERS = dict(_FALLBACK_FILTERS)
        _FILTERS_FETCHED_AT = now
        logger.warning("exchange_filters_using_fallback",
                       count=len(_FILTERS),
                       reason="no cached data and fetch failed")
    return _FILTERS


def get_filters(symbol: str) -> dict:
    """Get filters for one symbol. Triggers refresh if cache is empty/stale.
    Returns the default fallback if symbol is not in exchangeInfo."""
    if not _FILTERS or (time.time() - _FILTERS_FETCHED_AT > _CACHE_TTL_SEC):
        refresh_filters()
    return _FILTERS.get(symbol, _DEFAULT_FALLBACK)


def round_qty(symbol: str, qty: float) -> float:
    """Round quantity DOWN to the nearest stepSize multiple (never round up
    to avoid accidentally exceeding available margin)."""
    f = get_filters(symbol)
    step = f["stepSize"]
    if step <= 0:
        return qty
    # Decimal arithmetic to avoid float precision errors like 0.1 + 0.2
    q = Decimal(str(qty))
    s = Decimal(str(step))
    rounded = (q / s).to_integral_value(rounding=ROUND_DOWN) * s
    return float(rounded)


def round_price(symbol: str, price: float) -> float:
    """Round price to the nearest tickSize. Uses banker's rounding via Decimal."""
    f = get_filters(symbol)
    tick = f["tickSize"]
    if tick <= 0:
        return price
    p = Decimal(str(price))
    t = Decimal(str(tick))
    rounded = (p / t).to_integral_value(rounding=ROUND_DOWN) * t
    return float(rounded)


def validate_order(symbol: str, qty: float, price: float = 0.0) -> tuple[bool, str]:
    """Local pre-submit validation. Returns (valid, reason).

    Checks:
      1. qty > 0
      2. qty >= minQty
      3. qty is a multiple of stepSize (after rounding)
      4. If price > 0: qty * price >= minNotional
    """
    if qty <= 0:
        return False, "qty_non_positive"
    f = get_filters(symbol)
    if qty < f["minQty"]:
        return False, f"qty_below_minQty ({qty} < {f['minQty']})"
    # Post-rounding multiple check
    if f["stepSize"] > 0:
        ratio = Decimal(str(qty)) / Decimal(str(f["stepSize"]))
        if ratio != ratio.to_integral_value(rounding=ROUND_DOWN):
            return False, f"qty_not_step_multiple ({qty} not multiple of {f['stepSize']})"
    if price > 0:
        notional = qty * price
        if notional < f["minNotional"]:
            return False, f"notional_below_min ({notional:.4f} < {f['minNotional']})"
    return True, ""


def format_qty_canonical(asset: str, qty: float) -> tuple[str, dict]:
    """Canonical replacement for the old _format_qty().

    Returns (formatted_qty_str, adjustments_log):
      adjustments_log = {
        'original_qty': float,
        'rounded_qty': float,
        'stepSize': float,
        'source': 'binance_exchange_info' | 'fallback' | 'fallback_default',
        'symbol': str,
      }

    If the rounded qty is 0 (below stepSize), the formatted_qty_str is
    'INVALID_BELOW_STEP' — callers should NOT submit this order.
    """
    from bahamut.execution.binance_futures import _to_symbol
    symbol = _to_symbol(asset)
    f = get_filters(symbol)
    rounded = round_qty(symbol, qty)
    precision = f["quantity_precision"]
    adjustments = {
        "original_qty": float(qty),
        "rounded_qty": rounded,
        "stepSize": f["stepSize"],
        "minQty": f["minQty"],
        "minNotional": f["minNotional"],
        "source": f.get("source", "unknown"),
        "symbol": symbol,
        "adjustment_delta": round(qty - rounded, 10),
    }
    if rounded <= 0:
        adjustments["error"] = f"qty {qty} rounds to 0 below stepSize {f['stepSize']}"
        return "INVALID_BELOW_STEP", adjustments
    return f"{rounded:.{precision}f}", adjustments
