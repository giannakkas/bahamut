"""
Bahamut Live Data Provider

Fetches real 4H candles from Twelve Data API for BTCUSD and ETHUSD.
Validates data integrity, caches in Redis, falls back to synthetic.

Usage:
    candles = fetch_candles("BTCUSD")  # returns list of validated candle dicts
"""
import os
import json
import time
import asyncio
import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()

# ── Constants ──
SUPPORTED_ASSETS = {"BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD"}
CANDLE_COUNT = 260          # Need 260 for EMA200 + buffer
CACHE_TTL = 180             # 3 minutes — plenty for 4H bars
STALE_THRESHOLD = 6 * 3600  # 6 hours — default for 24/7 assets (crypto)


# ═══════════════════════════════════════════════════════════════
# Phase 4 Item 12 — DATA MODE PROVENANCE
# ═══════════════════════════════════════════════════════════════
# Every candle returned by fetch_candles() carries a _data_mode tag.
# Downstream code (orchestrator, engine, learning) MUST honor this:
#
#   "live"          — fresh candles from a real exchange/data API
#   "stale_cache"   — last_good Redis snapshot (real data, but old)
#   "synthetic_dev" — generated np.random data — DEV ONLY
#
# Production must never trade on synthetic_dev data:
#   BAHAMUT_BLOCK_SYNTHETIC=1 (default ON) → fetch_candles returns []
#   instead of generated candles. Orchestrator skips the asset.
#   Set to 0 ONLY in dev environments where synthetic data is desired
#   for offline testing.
DATA_MODE_LIVE = "live"
DATA_MODE_STALE_CACHE = "stale_cache"
DATA_MODE_SYNTHETIC_DEV = "synthetic_dev"

# Default ON: synthetic data is BLOCKED in production. Set to 0 only
# in dev environments where you want offline testing with seeded data.
BLOCK_SYNTHETIC = os.environ.get("BAHAMUT_BLOCK_SYNTHETIC", "1") != "0"


def _get_stale_threshold(asset: str = "") -> int:
    """Get stale threshold in seconds, adjusted for market hours.

    Crypto: 6h (24/7)
    Forex: 8h (nearly 24/5)
    Stock/Index: 6h during US market hours, 66h outside (covers weekend)
    Commodity: 8h
    """
    try:
        from bahamut.config_assets import ASSET_CLASS_MAP
        asset_class = ASSET_CLASS_MAP.get(asset, "")
    except Exception:
        asset_class = ""

    if asset_class in ("stock", "index"):
        if _is_us_market_open():
            return 6 * 3600      # 6h during market hours
        else:
            return 66 * 3600     # 66h covers Fri 4pm → Mon 9:30am ET
    elif asset_class == "forex":
        return 8 * 3600          # Forex is nearly 24h on weekdays
    elif asset_class == "commodity":
        return 8 * 3600
    else:
        return 6 * 3600          # Crypto is 24/7


def _is_us_market_open() -> bool:
    """Check if US stock market is currently open (approx)."""
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    # Convert to ET (UTC-5 standard, UTC-4 DST)
    # Approximate: use UTC-4 Mar-Nov, UTC-5 Nov-Mar
    month = now_utc.month
    et_offset = timedelta(hours=-4) if 3 <= month <= 10 else timedelta(hours=-5)
    now_et = now_utc + et_offset

    # Weekend check (Sat=5, Sun=6)
    if now_et.weekday() >= 5:
        return False

    # Market hours: 9:30 - 16:00 ET
    market_open = now_et.replace(hour=9, minute=30, second=0)
    market_close = now_et.replace(hour=16, minute=0, second=0)
    return market_open <= now_et <= market_close


def _tag_candles(candles: list[dict], mode: str) -> list[dict]:
    """Phase 4 Item 12: stamp every candle with its data_mode origin.

    Mutates in place AND returns the list for chaining. Downstream code
    can inspect candles[i].get('_data_mode') or take the consensus from
    the last candle.
    """
    for c in candles:
        c["_data_mode"] = mode
    return candles


def fetch_candles(asset: str, count: int = CANDLE_COUNT) -> list[dict]:
    """
    Fetch candles for an asset. Tries: Redis cache → Twelve Data API →
    last-good cache → synthetic fallback (if not blocked).

    Phase 4 Item 12: every returned candle carries a _data_mode tag of
    'live' / 'stale_cache' / 'synthetic_dev'. When BLOCK_SYNTHETIC=True
    (production default), the synthetic path returns [] instead of
    generated data — orchestrator must skip the asset.

    Returns candles in orchestrator format:
      [{datetime, open, high, low, close, volume, _data_mode}, ...]
    """
    source = "UNKNOWN"

    # 1. Try Redis cache (these are LIVE candles cached by an earlier fetch)
    cached = _cache_get(asset)
    if cached:
        logger.debug("data_cache_hit", asset=asset, candles=len(cached))
        # Cached candles inherit their original mode tag (set when first
        # fetched). If the tag is missing (legacy cache entries), assume
        # live — Redis only ever stored real Twelve Data candles.
        for c in cached:
            if "_data_mode" not in c:
                c["_data_mode"] = DATA_MODE_LIVE
        return cached

    # 2. Try Twelve Data API
    td_symbol = SUPPORTED_ASSETS.get(asset)
    if not td_symbol:
        # Training assets: fall through to the full symbol map
        try:
            from bahamut.ingestion.adapters.twelvedata import TWELVE_SYMBOL_MAP
            td_symbol = TWELVE_SYMBOL_MAP.get(asset)
        except ImportError:
            pass
    if td_symbol:
        try:
            candles = _fetch_from_twelvedata(td_symbol, count)
            if candles and len(candles) >= 50:
                # Validate
                valid, reason = validate_candles(candles, asset=asset)
                if valid:
                    _tag_candles(candles, DATA_MODE_LIVE)
                    _cache_set(asset, candles)
                    _record_data_status(asset, "OK", len(candles), candles[-1].get("datetime", ""))
                    logger.info("data_live", asset=asset, candles=len(candles),
                                last=candles[-1].get("datetime", ""),
                                close=candles[-1].get("close", 0),
                                data_mode=DATA_MODE_LIVE)
                    return candles
                else:
                    logger.warning("data_validation_failed", asset=asset, reason=reason)
        except Exception as e:
            logger.error("data_fetch_error", asset=asset, error=str(e))

    # 3. Try last known good data from Redis
    last_good = _cache_get(asset, key_suffix=":last_good")
    if last_good:
        logger.warning("data_using_last_good", asset=asset, candles=len(last_good))
        _record_data_status(asset, "STALE", len(last_good), "using cached data")
        return _tag_candles(last_good, DATA_MODE_STALE_CACHE)

    # 4. Phase 4 Item 12: synthetic block in production
    if BLOCK_SYNTHETIC:
        logger.error("data_synthetic_blocked",
                     asset=asset,
                     reason="no live data and BAHAMUT_BLOCK_SYNTHETIC=1",
                     action="returning empty list — orchestrator must skip asset")
        _record_data_status(asset, "UNAVAILABLE", 0,
                            "live unavailable, synthetic blocked")
        # Increment a counter so diagnostics shows how often this fires
        _increment_synthetic_block_counter()
        return []

    # 5. Fallback to synthetic (DEV ONLY — block flag is off)
    logger.warning("data_fallback_synthetic", asset=asset,
                   warning="DEV MODE — synthetic data in use")
    _record_data_status(asset, "SYNTHETIC", 0, "DEV: live data unavailable")
    return _tag_candles(_synthetic_fallback(asset), DATA_MODE_SYNTHETIC_DEV)


def _increment_synthetic_block_counter():
    """Track how many times we've refused to serve synthetic data."""
    try:
        import redis as _r
        r = _r.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                        socket_connect_timeout=1)
        r.incr("bahamut:counters:synthetic_blocks")
    except Exception:
        pass


def _fetch_from_twelvedata(symbol: str, count: int) -> list[dict]:
    """Fetch from Twelve Data API (sync wrapper around async adapter).

    Adds closed-candle enforcement + provenance fields. Twelve Data /time_series
    returns closed bars by convention, but we still verify the last bar's
    open_time vs now to detect any forming-bar contamination.
    """
    from bahamut.ingestion.adapters.twelvedata import twelve_data

    if not twelve_data.configured:
        logger.debug("twelvedata_not_configured")
        return []

    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(twelve_data.get_candles(symbol, "4h", count))
    finally:
        loop.close()

    if not raw:
        return []

    # Convert from TwelveData format (time) to orchestrator format (datetime)
    # and add provenance fields.
    # Twelve Data 4H bar open_time + 4h = close_time.
    now_ts = int(time.time())
    _INTERVAL_SEC_4H = 14400
    candles = []
    for c in raw:
        dt_str = c.get("time", c.get("datetime", ""))
        # Parse open_time for closed-state verification
        open_time_ts = 0
        try:
            if dt_str:
                # Twelve Data returns "YYYY-MM-DD HH:MM:SS" in UTC
                from datetime import datetime as _dt
                parsed = _dt.strptime(dt_str, "%Y-%m-%d %H:%M:%S") if " " in dt_str else _dt.fromisoformat(dt_str.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                open_time_ts = int(parsed.timestamp())
        except Exception:
            pass
        close_time_ts = open_time_ts + _INTERVAL_SEC_4H if open_time_ts else 0
        # For Twelve Data: bar is closed when now > close_time
        is_closed = (now_ts > close_time_ts) if close_time_ts > 0 else True
        candles.append({
            "datetime": dt_str,
            "open": float(c.get("open", 0)),
            "high": float(c.get("high", 0)),
            "low": float(c.get("low", 0)),
            "close": float(c.get("close", 0)),
            "volume": float(c.get("volume", 0)),
            # Provenance
            "open_time": open_time_ts * 1000 if open_time_ts else 0,
            "close_time": close_time_ts * 1000 if close_time_ts else 0,
            "is_closed": is_closed,
            "source": "twelvedata",
        })

    # Drop any trailing forming candle — Twelve Data rarely sends one, but
    # defense in depth: strategies must never see open bars.
    dropped_forming = 0
    while candles and not candles[-1]["is_closed"]:
        candles.pop()
        dropped_forming += 1

    if dropped_forming > 0:
        logger.warning("twelvedata_dropped_forming_candle",
                       symbol=symbol, dropped=dropped_forming)

    # Record to shared diagnostics state
    try:
        from bahamut.data.binance_data import _LAST_CANDLE_STATE
        if candles:
            last = candles[-1]
            _LAST_CANDLE_STATE[f"{symbol}:4h"] = {
                "last_open_time": last["open_time"],
                "last_close_time": last["close_time"],
                "last_datetime": last["datetime"],
                "is_closed": last["is_closed"],
                "dropped_forming": dropped_forming,
                "used_for_signals": True,
                "source": "twelvedata",
                "recorded_at": now_ts,
            }
    except Exception:
        pass

    return candles


def _synthetic_fallback(asset: str) -> list[dict]:
    """Fall back to synthetic data generator."""
    try:
        from bahamut.backtesting.data_real import get_asset_data
        return get_asset_data(asset)
    except Exception:
        return []


# ═══════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════

def validate_candles(candles: list[dict], asset: str = "") -> tuple[bool, str]:
    """
    Validate candle data integrity.
    Returns (is_valid, reason).
    """
    if not candles:
        return False, "empty candle list"

    if len(candles) < 50:
        return False, f"too few candles ({len(candles)}, need 50+)"

    # Check timestamps are increasing
    prev_ts = ""
    for i, c in enumerate(candles):
        ts = c.get("datetime", "")
        if not ts:
            return False, f"missing timestamp at index {i}"
        if ts <= prev_ts and prev_ts:
            return False, f"timestamps not increasing at index {i}: {prev_ts} >= {ts}"
        prev_ts = ts

    # Check last candle is not too old
    last_ts = candles[-1].get("datetime", "")
    try:
        last_dt = _parse_timestamp(last_ts)
        now = datetime.now(timezone.utc)
        age = (now - last_dt).total_seconds()
        threshold = _get_stale_threshold(asset)
        if age > threshold:
            return False, f"last candle is {age/3600:.1f}h old (stale)"
        if last_dt > now + timedelta(hours=1):
            return False, f"last candle is in the future: {last_ts}"
    except Exception as e:
        return False, f"cannot parse last timestamp '{last_ts}': {e}"

    # Check OHLC values are positive
    for i, c in enumerate(candles[-10:]):  # Check last 10
        for field in ["open", "high", "low", "close"]:
            val = c.get(field, 0)
            if not val or val <= 0:
                return False, f"invalid {field}={val} at index {len(candles)-10+i}"

    return True, "ok"


def _parse_timestamp(ts: str) -> datetime:
    """Parse various timestamp formats from Twelve Data."""
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00"]:
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Try ISO format
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ═══════════════════════════════════════════════════════
# NEW BAR DETECTION
# ═══════════════════════════════════════════════════════

_last_bar_timestamps: dict[str, str] = {}
_bar_state_initialized: bool = False


def is_new_bar(asset: str, current_timestamp: str) -> bool:
    """Check if this is a new 4H bar for this asset. READ-ONLY — does NOT advance state.
    Call mark_bar_processed() after successful processing."""
    _ensure_bar_state_loaded()
    last = _last_bar_timestamps.get(asset, "")

    if current_timestamp and current_timestamp != last:
        return True
    return False


def mark_bar_processed(asset: str, bar_timestamp: str):
    """Commit: mark a bar as successfully processed for this asset.
    Writes to: memory → Redis (cache) → DB (durable).
    Call ONLY after the asset's processing completes successfully."""
    _last_bar_timestamps[asset] = bar_timestamp

    # Redis (fast cache, survives worker restarts within same deploy)
    r = _get_redis()
    if r:
        try:
            r.set(f"bahamut:last_bar:{asset}", bar_timestamp)
        except Exception:
            pass

    # DB (durable, survives Redis flush and full restart)
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO bar_processing_state (asset, last_processed_bar, updated_at)
                VALUES (:asset, :ts, NOW())
                ON CONFLICT (asset) DO UPDATE SET
                    last_processed_bar = EXCLUDED.last_processed_bar,
                    updated_at = NOW()
            """), {"asset": asset, "ts": bar_timestamp})
            conn.commit()
    except Exception as e:
        logger.warning("bar_state_db_write_failed", asset=asset, error=str(e))

    logger.info("bar_processed_committed", asset=asset, bar=bar_timestamp)


def get_last_bar_timestamp(asset: str) -> str:
    """Get last processed bar timestamp for an asset.

    Always checks Redis first (written by worker process, read by API process).
    Falls back to in-memory cache if Redis is unavailable.
    """
    # Redis is the cross-process source of truth (worker writes, API reads)
    r = _get_redis()
    if r:
        try:
            stored = r.get(f"bahamut:last_bar:{asset}")
            if stored:
                ts = stored.decode() if isinstance(stored, bytes) else stored
                _last_bar_timestamps[asset] = ts  # Update local cache
                return ts
        except Exception:
            pass

    # Fallback: in-memory (may be stale in API process)
    _ensure_bar_state_loaded()
    return _last_bar_timestamps.get(asset, "")


def _ensure_bar_state_loaded():
    """On first access, load bar state from DB → Redis → memory.
    DB is canonical. Redis is cache. Memory is hot path."""
    global _bar_state_initialized
    if _bar_state_initialized:
        return

    _bar_state_initialized = True

    # 1. Try DB (canonical durable source)
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT asset, last_processed_bar FROM bar_processing_state"
            )).mappings().all()
            for row in rows:
                asset = row["asset"]
                ts = row["last_processed_bar"]
                if ts:
                    _last_bar_timestamps[asset] = ts
                    # Backfill Redis cache
                    r = _get_redis()
                    if r:
                        try:
                            r.set(f"bahamut:last_bar:{asset}", ts)
                        except Exception:
                            pass
            if rows:
                logger.info("bar_state_loaded_from_db",
                            assets={row["asset"]: row["last_processed_bar"] for row in rows})
                return
    except Exception as e:
        logger.warning("bar_state_db_load_failed", error=str(e))

    # 2. Fallback: try Redis (survives worker restart but not Redis flush)
    r = _get_redis()
    if r:
        try:
            for asset in ["BTCUSD", "ETHUSD"]:
                stored = r.get(f"bahamut:last_bar:{asset}")
                if stored:
                    ts = stored.decode() if isinstance(stored, bytes) else stored
                    _last_bar_timestamps[asset] = ts
            if _last_bar_timestamps:
                logger.info("bar_state_loaded_from_redis", assets=dict(_last_bar_timestamps))
                return
        except Exception as e:
            logger.warning("bar_state_redis_load_failed", error=str(e))

    logger.info("bar_state_cold_start", note="no previous bar state found")


# ═══════════════════════════════════════════════════════
# REDIS CACHE
# ═══════════════════════════════════════════════════════

def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _cache_get(asset: str, key_suffix: str = "") -> list[dict]:
    r = _get_redis()
    if r:
        try:
            raw = r.get(f"bahamut:candles:{asset}{key_suffix}")
            if raw:
                data = json.loads(raw)
                return data
        except Exception:
            pass
    return None


def _cache_set(asset: str, candles: list[dict]):
    r = _get_redis()
    if r:
        try:
            r.setex(f"bahamut:candles:{asset}", CACHE_TTL, json.dumps(candles))
            # Also store as last_good (longer TTL for fallback)
            r.setex(f"bahamut:candles:{asset}:last_good", 3600, json.dumps(candles))
        except Exception:
            pass


def _record_data_status(asset: str, status: str, candle_count: int, detail: str):
    """Record data status in Redis for health endpoint."""
    r = _get_redis()
    if r:
        try:
            r.hset("bahamut:data_status", asset, json.dumps({
                "status": status,
                "candles": candle_count,
                "detail": detail,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            pass


def get_data_status() -> dict:
    """Get data status for all assets (for health endpoint)."""
    r = _get_redis()
    result = {}
    if r:
        try:
            raw = r.hgetall("bahamut:data_status")
            for k, v in raw.items():
                key = k.decode() if isinstance(k, bytes) else k
                result[key] = json.loads(v)
        except Exception:
            pass
    return result


def get_data_source() -> str:
    """Return current data source: LIVE or SYNTHETIC."""
    try:
        from bahamut.ingestion.adapters.twelvedata import twelve_data
        if twelve_data.configured:
            return "LIVE"
    except Exception:
        pass
    return "SYNTHETIC"
