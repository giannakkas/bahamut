"""
Bahamut.AI — Funding Rate Tracker for Crypto Futures

Tracks estimated funding rate costs for open futures positions.
Binance Futures charges funding every 8 hours (00:00, 08:00, 16:00 UTC).

This module:
  1. Fetches current funding rate from Binance (free, public)
  2. Estimates accumulated cost for open positions
  3. Logs warnings when funding is abnormally high (> 0.05%)

Does NOT auto-deduct from PnL — that requires exchange-confirmed data.
Instead, provides estimated costs for monitoring and diagnostics.
"""
import os
import time
import httpx
import structlog

logger = structlog.get_logger()

BINANCE_PUBLIC_URL = "https://api.binance.com"

# Symbol mapping (same as binance_data.py)
_SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT", "LINKUSD": "LINKUSDT",
    "MATICUSD": "MATICUSDT", "DOTUSD": "DOTUSDT", "ATOMUSD": "ATOMUSDT",
}

# Cache: {symbol: {rate, timestamp}}
_RATE_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes


def get_funding_rate(asset: str) -> float | None:
    """Get current funding rate for a crypto asset from Binance.

    Returns rate as a decimal (e.g., 0.0001 = 0.01%).
    Positive rate: longs pay shorts. Negative: shorts pay longs.
    Returns None if unavailable.
    """
    symbol = _SYMBOL_MAP.get(asset)
    if not symbol:
        return None

    # Check cache
    cached = _RATE_CACHE.get(symbol)
    if cached and time.time() - cached["timestamp"] < _CACHE_TTL:
        return cached["rate"]

    try:
        r = httpx.get(
            f"{BINANCE_PUBLIC_URL}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            rate = float(data.get("lastFundingRate", 0))
            _RATE_CACHE[symbol] = {"rate": rate, "timestamp": time.time()}
            return rate
    except Exception as e:
        logger.debug("funding_rate_fetch_failed", asset=asset, error=str(e)[:50])

    return None


def estimate_funding_cost(
    asset: str,
    direction: str,
    notional_value: float,
    hours_held: float,
) -> dict:
    """Estimate accumulated funding cost for a position.

    Args:
        asset: Bahamut symbol (e.g., "BTCUSD")
        direction: "LONG" or "SHORT"
        notional_value: position size in USD
        hours_held: how long the position has been open

    Returns dict with:
        rate: current funding rate (decimal)
        funding_intervals: number of 8h intervals the position has been open
        estimated_cost: total estimated funding cost (positive = cost, negative = received)
        is_high: True if rate > 0.05% (annualized ~22%)
    """
    rate = get_funding_rate(asset)
    if rate is None:
        return {
            "rate": None,
            "funding_intervals": 0,
            "estimated_cost": 0,
            "is_high": False,
            "available": False,
        }

    intervals = int(hours_held / 8)  # funding every 8 hours

    # Positive rate: longs pay, shorts receive
    # Negative rate: shorts pay, longs receive
    if direction == "LONG":
        cost_per_interval = notional_value * rate  # positive = cost
    else:
        cost_per_interval = -notional_value * rate  # flip sign for shorts

    total_cost = cost_per_interval * max(1, intervals)
    is_high = abs(rate) > 0.0005  # 0.05% per 8h = ~22% annualized

    if is_high:
        logger.warning("funding_rate_high",
                        asset=asset, rate=round(rate * 100, 4),
                        direction=direction,
                        estimated_cost=round(total_cost, 2),
                        intervals=intervals)

    return {
        "rate": round(rate, 6),
        "rate_pct": round(rate * 100, 4),
        "funding_intervals": intervals,
        "estimated_cost": round(total_cost, 2),
        "is_high": is_high,
        "available": True,
    }


def check_all_positions_funding(positions: list[dict]) -> list[dict]:
    """Check funding costs for a list of open positions.

    positions: list of dicts with keys: asset, direction, size, entry_price, entry_time
    Returns list of funding cost estimates.
    """
    from datetime import datetime, timezone

    results = []
    now = datetime.now(timezone.utc)

    for pos in positions:
        asset = pos.get("asset", "")
        direction = pos.get("direction", "LONG")
        size = float(pos.get("size", 0))
        entry_price = float(pos.get("entry_price", 0))
        entry_time = pos.get("entry_time", "")

        if not asset or size <= 0 or entry_price <= 0:
            continue

        # Only for crypto futures
        if asset not in _SYMBOL_MAP:
            continue

        notional = size * entry_price

        # Calculate hours held
        hours = 0
        if entry_time:
            try:
                if isinstance(entry_time, str):
                    et = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                else:
                    et = entry_time
                hours = (now - et).total_seconds() / 3600
            except Exception:
                hours = 0

        estimate = estimate_funding_cost(asset, direction, notional, hours)
        estimate["asset"] = asset
        estimate["direction"] = direction
        estimate["notional"] = round(notional, 2)
        estimate["hours_held"] = round(hours, 1)
        results.append(estimate)

    return results


def accrue_funding_for_all_positions() -> dict:
    """Update funding_accrued on all open crypto training positions.

    Should be called every 8 hours aligned to Binance funding windows.
    Returns summary of accruals.
    """
    summary = {"positions_updated": 0, "total_accrued": 0.0, "errors": []}
    try:
        from bahamut.trading.engine import _load_positions, _get_redis
        from bahamut.execution.binance_futures import SYMBOL_MAP

        positions = _load_positions()
        crypto_positions = [p for p in positions
                           if getattr(p, "asset_class", "") == "crypto"
                           and getattr(p, "execution_platform", "")
                           in ("binance", "binance_futures")]

        if not crypto_positions:
            return summary

        for pos in crypto_positions:
            try:
                symbol = SYMBOL_MAP.get(pos.asset, pos.asset.replace("USD", "USDT"))
                rate = get_funding_rate(pos.asset)
                if rate is None or rate == 0:
                    continue

                notional = abs(pos.size * pos.current_price)
                # Positive rate: longs pay shorts
                if pos.direction == "LONG":
                    cost = notional * rate
                else:
                    cost = -notional * rate

                current = getattr(pos, "funding_accrued", 0) or 0
                new_total = round(current + cost, 6)

                # Persist to Redis
                r = _get_redis()
                if r:
                    pos_key = f"bahamut:training_pos:{pos.position_id}"
                    r.hset(pos_key, "funding_accrued", str(new_total))

                # Persist to DB
                from bahamut.database import sync_engine
                from sqlalchemy import text
                with sync_engine.connect() as conn:
                    conn.execute(text(
                        "UPDATE training_positions SET funding_accrued = :fa "
                        "WHERE position_id = :pid"
                    ), {"fa": new_total, "pid": pos.position_id})
                    conn.commit()

                summary["positions_updated"] += 1
                summary["total_accrued"] += cost
                logger.info("funding_accrued",
                            asset=pos.asset, direction=pos.direction,
                            rate=rate, cost=round(cost, 4),
                            total_accrued=new_total)
            except Exception as e:
                summary["errors"].append(f"{pos.asset}: {str(e)[:80]}")

    except Exception as e:
        summary["errors"].append(f"global: {str(e)[:100]}")
        logger.error("funding_accrual_failed", error=str(e)[:200])

    return summary
