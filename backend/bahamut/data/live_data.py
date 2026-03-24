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
STALE_THRESHOLD = 6 * 3600  # 6 hours — more than one 4H bar


def fetch_candles(asset: str, count: int = CANDLE_COUNT) -> list[dict]:
    """
    Fetch candles for an asset. Tries: Redis cache → Twelve Data API → synthetic fallback.
    Returns candles in orchestrator format: [{datetime, open, high, low, close, volume}, ...]
    """
    source = "UNKNOWN"

    # 1. Try Redis cache
    cached = _cache_get(asset)
    if cached:
        logger.debug("data_cache_hit", asset=asset, candles=len(cached))
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
                valid, reason = validate_candles(candles)
                if valid:
                    _cache_set(asset, candles)
                    _record_data_status(asset, "OK", len(candles), candles[-1].get("datetime", ""))
                    logger.info("data_live", asset=asset, candles=len(candles),
                                last=candles[-1].get("datetime", ""),
                                close=candles[-1].get("close", 0))
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
        return last_good

    # 4. Fallback to synthetic
    logger.warning("data_fallback_synthetic", asset=asset)
    _record_data_status(asset, "SYNTHETIC", 0, "live data unavailable")
    return _synthetic_fallback(asset)


def _fetch_from_twelvedata(symbol: str, count: int) -> list[dict]:
    """Fetch from Twelve Data API (sync wrapper around async adapter)."""
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
    candles = []
    for c in raw:
        candles.append({
            "datetime": c.get("time", c.get("datetime", "")),
            "open": float(c.get("open", 0)),
            "high": float(c.get("high", 0)),
            "low": float(c.get("low", 0)),
            "close": float(c.get("close", 0)),
            "volume": float(c.get("volume", 0)),
        })

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

def validate_candles(candles: list[dict]) -> tuple[bool, str]:
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
        if age > STALE_THRESHOLD:
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
