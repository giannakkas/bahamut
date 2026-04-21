"""
Bahamut.AI — Binance Public Market Data

FREE, NO API KEY, NO RATE LIMITS for market data.
Uses Binance's public REST API for candle/kline data.

This replaces Twelve Data for crypto assets, saving API quota
for stocks which still need Twelve Data.

Endpoints:
  GET /api/v3/klines — candlestick data (no auth required)
  GET /api/v3/ticker/price — current price (no auth required)
"""
import httpx
import structlog
import numpy as np
import time as _time
from datetime import datetime, timezone

logger = structlog.get_logger()

# Use production Binance for market data (public, free)
# Demo/testnet doesn't have reliable market data
BINANCE_PUBLIC_URL = "https://api.binance.com"
BINANCE_FUTURES_URL = "https://fapi.binance.com"

# ─────────────────────────────────────────────────────────────
# CLOSED-CANDLE ENFORCEMENT
# ─────────────────────────────────────────────────────────────
# Binance /api/v3/klines returns the in-progress candle as the last element.
# Using it for signals means we're acting on partial OHLC that can reverse
# before the bar closes. Every path that feeds strategies MUST use closed
# candles only.
#
# We enforce this by:
#   1. Requesting limit+1 candles so we always have the limit we need even
#      after dropping the forming bar.
#   2. Marking each candle with is_closed (true/false) using timestamp math.
#   3. Dropping the in-progress candle from the returned list by default.
#   4. Exposing provenance fields (open_time, close_time, source).
#
# Callers that need the in-progress candle for live mark-to-market can call
# get_candles(..., include_forming=True) and filter by is_closed themselves.

_INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400,
}


def _interval_to_seconds(interval: str) -> int:
    return _INTERVAL_SECONDS.get(interval, 0)


# Diagnostics: last candle closed state per (asset, interval). In-memory only.
_LAST_CANDLE_STATE: dict = {}


def last_candle_closed_state() -> dict:
    """Return diagnostics for the last candle fetched per (asset, interval).
    Exposes: last_open_time, last_close_time, is_closed, dropped_forming, used_for_signals.
    """
    return dict(_LAST_CANDLE_STATE)


# Map Bahamut symbols to Binance pairs
SYMBOL_MAP = {
    # Tier 1
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT", "XRPUSD": "XRPUSDT",
    # Tier 2
    "ADAUSD": "ADAUSDT", "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT",
    "LINKUSD": "LINKUSDT", "MATICUSD": "MATICUSDT",
    # Tier 3
    "DOTUSD": "DOTUSDT", "ATOMUSD": "ATOMUSDT", "UNIUSD": "UNIUSDT",
    "LTCUSD": "LTCUSDT", "NEARUSD": "NEARUSDT", "ARBUSD": "ARBUSDT",
    "OPUSD": "OPUSDT", "FILUSD": "FILUSDT", "APTUSD": "APTUSDT",
    "INJUSD": "INJUSDT",
    # Tier 4
    "PEPEUSD": "PEPEUSDT", "WIFUSD": "WIFUSDT", "RNDRUSD": "RENDERUSDT",
    "FETUSD": "FETUSDT", "TIAUSD": "TIAUSDT", "SUIUSD": "SUIUSDT",
    "SEIUSD": "SEIUSDT", "JUPUSD": "JUPUSDT", "WUSD": "WUSDT",
    "ENAUSD": "ENAUSDT",
}


def get_candles(asset: str, interval: str = "15m", limit: int = 100,
                include_forming: bool = False) -> list[dict]:
    """Fetch candles from Binance public API with closed-candle enforcement.

    Binance returns the in-progress candle as the last kline. We drop it by
    default so strategies only see confirmed closed bars.

    Args:
        asset: Bahamut symbol (e.g. "BTCUSD")
        interval: Binance interval string: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d
        limit: number of CLOSED candles to return (we fetch limit+1 and drop the forming one)
        include_forming: if True, include the in-progress candle (marked is_closed=False).
                         Default False — signal/indicator code must never set this.

    Returns list of candle dicts with keys:
        open, high, low, close, volume, datetime,
        open_time, close_time, is_closed, source
    """
    symbol = SYMBOL_MAP.get(asset)
    if not symbol:
        logger.warning("binance_data_unknown_symbol", asset=asset)
        return []

    interval_sec = _interval_to_seconds(interval)
    # Request limit+1 so we still have `limit` closed bars after dropping the forming one
    fetch_limit = min(1000, limit + 1)

    try:
        # Try Spot API first, then Futures API as fallback.
        # Many newer tokens (WIF, JUP, FET, TIA, SEI, W, ENA) are only on
        # Binance Futures, not Spot. Both APIs use the same kline format.
        raw = None
        _kline_source = "binance_public"
        for _base_url, _path in [
            (BINANCE_PUBLIC_URL, "/api/v3/klines"),
            (BINANCE_FUTURES_URL, "/fapi/v1/klines"),
        ]:
            r = httpx.get(
                f"{_base_url}{_path}",
                params={"symbol": symbol, "interval": interval, "limit": fetch_limit},
                timeout=10,
            )
            if r.status_code == 200:
                _raw = r.json()
                if _raw and len(_raw) > 0:
                    raw = _raw
                    _kline_source = "binance_futures" if "fapi" in _path else "binance_public"
                    break
            # Log spot failure at debug, try futures next
            if "fapi" not in _path:
                logger.debug("binance_spot_klines_miss", asset=asset, status=r.status_code)

        if not raw:
            logger.warning("binance_klines_both_failed", asset=asset, symbol=symbol)
            return []

        now_ms = int(_time.time() * 1000)
        candles = []
        for k in raw:
            # Binance kline format: [open_time, open, high, low, close, volume,
            #                        close_time, quote_asset_volume, trades, ...]
            open_time_ms = int(k[0])
            close_time_ms = int(k[6])
            # A candle is CLOSED when current time is past close_time
            is_closed = now_ms >= close_time_ms

            ts = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).isoformat()
            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "datetime": ts,
                # Provenance fields
                "open_time": open_time_ms,
                "close_time": close_time_ms,
                "is_closed": is_closed,
                "source": _kline_source,
            })

        # Drop trailing forming candle(s) unless caller explicitly wants them
        dropped_forming = 0
        if not include_forming:
            while candles and not candles[-1]["is_closed"]:
                candles.pop()
                dropped_forming += 1

        # Diagnostics: record last candle state for this (asset, interval)
        if candles:
            last = candles[-1]
            _LAST_CANDLE_STATE[f"{asset}:{interval}"] = {
                "last_open_time": last["open_time"],
                "last_close_time": last["close_time"],
                "last_datetime": last["datetime"],
                "is_closed": last["is_closed"],
                "dropped_forming": dropped_forming,
                "used_for_signals": not include_forming,
                "source": last["source"],
                "recorded_at": int(_time.time()),
            }
            if not last["is_closed"] and not include_forming:
                # Should never happen — belt-and-suspenders
                logger.error("closed_candle_enforcement_violation",
                             asset=asset, interval=interval,
                             last_datetime=last["datetime"])
        return candles

    except Exception as e:
        logger.warning("binance_klines_exception", asset=asset, error=str(e)[:100])
        return []


def get_price(asset: str) -> float:
    """Get current price from Binance (free, no key). Tries Spot then Futures."""
    symbol = SYMBOL_MAP.get(asset)
    if not symbol:
        return 0.0
    for _base, _path in [
        (BINANCE_PUBLIC_URL, "/api/v3/ticker/price"),
        (BINANCE_FUTURES_URL, "/fapi/v1/ticker/price"),
    ]:
        try:
            r = httpx.get(f"{_base}{_path}", params={"symbol": symbol}, timeout=5)
            if r.status_code == 200:
                price = float(r.json().get("price", 0))
                if price > 0:
                    return price
        except Exception:
            pass
    return 0.0


def validate_candle_continuity(candles: list[dict], interval: str = "15m") -> dict:
    """Check that candles are contiguous (no gaps).

    Returns dict with is_valid, gap_count, gaps (list of gap details).
    Gaps can occur when an exchange has maintenance or API returns incomplete data.
    Missing candles silently break EMA/ATR continuity.
    """
    result = {"is_valid": True, "gap_count": 0, "gaps": []}

    if not candles or len(candles) < 2:
        return result

    expected_ms = _INTERVAL_SECONDS.get(interval, 0) * 1000
    if expected_ms == 0:
        return result

    for i in range(1, len(candles)):
        ot_curr = candles[i].get("open_time", 0)
        ot_prev = candles[i - 1].get("open_time", 0)
        if ot_curr and ot_prev:
            diff = ot_curr - ot_prev
            if diff != expected_ms:
                missing_bars = (diff // expected_ms) - 1
                result["gaps"].append({
                    "index": i,
                    "expected_ms": expected_ms,
                    "actual_ms": diff,
                    "missing_bars": int(missing_bars),
                    "datetime": candles[i].get("datetime", ""),
                })

    result["gap_count"] = len(result["gaps"])
    result["is_valid"] = result["gap_count"] == 0

    if result["gap_count"] > 0:
        total_missing = sum(g["missing_bars"] for g in result["gaps"])
        logger.warning("candle_gap_detected",
                        interval=interval,
                        gap_count=result["gap_count"],
                        total_missing_bars=total_missing,
                        first_gap_at=result["gaps"][0]["datetime"] if result["gaps"] else "")

    return result


def compute_indicators(candles: list[dict], interval: str = "15m") -> dict:
    """Compute technical indicators from Binance candles.

    CANONICAL: delegates to bahamut.features.indicators.compute_indicators so
    crypto and stock paths share one indicator math implementation. Previously
    this module had its own simpler (and less correct) math — notably RSI/ATR
    without Wilder smoothing and a single-period unsmoothed DX as 'ADX'. That
    produced materially different values for the same data vs the stock path
    and made v8 regime detection asset-class-dependent.

    HARD INVARIANT: the last candle must be closed. If is_closed=False we
    drop it. Legacy candles without the field are assumed closed.

    Return contract is unchanged — existing callers read the same keys.
    Indicator provenance fields (indicator_engine_version, indicator_source)
    are added to make the engine identity visible in diagnostics.
    """
    if not candles or len(candles) < 30:
        return {}

    # Closed-candle invariant (kept here for defense-in-depth; features/indicators
    # has its own version that also fires if this one is bypassed)
    if candles and candles[-1].get("is_closed") is False:
        logger.warning("compute_indicators_dropping_forming_candle",
                       datetime=candles[-1].get("datetime", ""),
                       source=candles[-1].get("source", "unknown"))
        candles = candles[:-1]
        if len(candles) < 30:
            return {}

    from bahamut.features.indicators import compute_indicators as canonical
    result = canonical(candles, interval=interval)
    if not result:
        return {}

    # Provenance: which engine produced these values?
    result["indicator_engine_version"] = INDICATOR_ENGINE_VERSION
    result["indicator_source"] = "canonical_via_binance_wrapper"
    return result


# Version bump this when indicator math changes to invalidate downstream caches.
INDICATOR_ENGINE_VERSION = "v2.1-canonical-2026-04-17"


def is_crypto(asset: str) -> bool:
    """Check if an asset should use Binance data."""
    return asset in SYMBOL_MAP

