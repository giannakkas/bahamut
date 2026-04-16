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
    "PEPEUSD": "PEPEUSDT", "WIFUSD": "WIFUSDT", "RNDRUSD": "RNDRUSDT",
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
        r = httpx.get(
            f"{BINANCE_PUBLIC_URL}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": fetch_limit},
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning("binance_klines_error", asset=asset, status=r.status_code)
            return []

        raw = r.json()
        if not raw:
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
                "source": "binance_public",
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
    """Get current price from Binance (free, no key)."""
    symbol = SYMBOL_MAP.get(asset)
    if not symbol:
        return 0.0
    try:
        r = httpx.get(
            f"{BINANCE_PUBLIC_URL}/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=5,
        )
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    return 0.0


def compute_indicators(candles: list[dict]) -> dict:
    """Compute technical indicators from Binance candles.

    Returns same indicator dict format as Twelve Data compute_indicators(),
    so strategies work without changes.

    HARD INVARIANT: the last candle must be closed. If it has an is_closed
    field equal to False, we drop it before computing indicators. This
    prevents strategies from acting on in-progress bars.
    """
    if not candles or len(candles) < 30:
        return {}

    # Closed-candle invariant: strip any trailing forming bar.
    # Callers that produced this list with include_forming=True will have
    # is_closed=False on the last element. Legacy lists without is_closed
    # are assumed closed (backward compatibility for non-Binance sources).
    if candles and candles[-1].get("is_closed") is False:
        logger.warning("compute_indicators_dropping_forming_candle",
                       datetime=candles[-1].get("datetime", ""),
                       source=candles[-1].get("source", "unknown"))
        candles = candles[:-1]
        if len(candles) < 30:
            return {}

    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    close = closes[-1]

    # EMAs
    def _ema(data, period):
        if len(data) < period:
            return float(np.mean(data))
        alpha = 2 / (period + 1)
        ema = data[0]
        for val in data[1:]:
            ema = alpha * val + (1 - alpha) * ema
        return float(ema)

    ema_20 = _ema(closes, 20)
    ema_50 = _ema(closes, 50)
    ema_200 = _ema(closes, 200) if len(closes) >= 200 else _ema(closes, min(len(closes), 100))

    # RSI
    deltas = np.diff(closes[-15:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
    rs = avg_gain / max(avg_loss, 0.0001)
    rsi = 100 - (100 / (1 + rs))

    # ATR
    trs = []
    for i in range(max(1, len(candles) - 14), len(candles)):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1] if i > 0 else l
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr = float(np.mean(trs)) if trs else 0

    # Bollinger Bands (20-period, 2 std dev)
    bb_data = closes[-20:]
    bb_mid = float(np.mean(bb_data))
    bb_std = float(np.std(bb_data))
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # ADX (simplified)
    adx = 25.0  # Default neutral
    if len(candles) >= 20:
        dm_plus = []
        dm_minus = []
        for i in range(max(1, len(candles) - 14), len(candles)):
            up = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]
            dm_plus.append(up if up > down and up > 0 else 0)
            dm_minus.append(down if down > up and down > 0 else 0)
        if trs and sum(trs) > 0:
            di_plus = sum(dm_plus) / max(sum(trs), 0.001) * 100
            di_minus = sum(dm_minus) / max(sum(trs), 0.001) * 100
            dx = abs(di_plus - di_minus) / max(di_plus + di_minus, 0.001) * 100
            adx = dx

    return {
        "close": close,
        "open": float(candles[-1]["open"]),
        "high": float(candles[-1]["high"]),
        "low": float(candles[-1]["low"]),
        "volume": float(candles[-1]["volume"]),
        "ema_20": round(ema_20, 6),
        "ema_50": round(ema_50, 6),
        "ema_200": round(ema_200, 6),
        "rsi_14": round(float(rsi), 2),
        "atr_14": round(atr, 6),
        "adx_14": round(adx, 2),
        "bollinger_upper": round(bb_upper, 6),
        "bollinger_mid": round(bb_mid, 6),
        "bollinger_lower": round(bb_lower, 6),
    }


def is_crypto(asset: str) -> bool:
    """Check if an asset should use Binance data."""
    return asset in SYMBOL_MAP
