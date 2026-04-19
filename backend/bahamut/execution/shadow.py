"""
Shadow mode: full trading logic, but broker calls are logged not executed.

When BAHAMUT_SHADOW_MODE=1, execute_open/execute_close return simulated
ExecutionResults instead of calling real brokers. All other logic runs
identically — same selectors, gauntlet, risk budget, persistence.

Used to validate code changes against production parallel-running
without real-money risk.

Deploy: separate Railway env with BAHAMUT_SHADOW_MODE=1, own Redis + Postgres.
"""
import os
import time
import structlog

logger = structlog.get_logger()

SHADOW_MODE = os.environ.get("BAHAMUT_SHADOW_MODE", "0").lower() in ("1", "true")


def is_shadow() -> bool:
    """Check if running in shadow mode."""
    return SHADOW_MODE


def simulate_open(asset: str, asset_class: str, direction: str,
                  size: float, risk_amount: float = 0) -> dict:
    """Simulate an open execution using recent price from Redis cache.

    Returns a realistic ExecutionResult dict without calling any broker.
    """
    price = _get_recent_price(asset)
    slippage_bps = 10 if asset_class == "crypto" else 15

    if direction == "LONG":
        fill_price = price * (1 + slippage_bps / 10000)
    else:
        fill_price = price * (1 - slippage_bps / 10000)

    result = {
        "platform": f"shadow_{asset_class}",
        "order_id": f"shadow_{asset}_{int(time.time())}",
        "client_order_id": f"shadow_bah_{asset.lower()}_{int(time.time()*1000)}",
        "fill_price": round(fill_price, 6),
        "fill_qty": size,
        "status": "FILLED",
        "lifecycle": "FILLED",
        "commission": round(size * fill_price * 0.0004, 4),  # 4bps taker
        "slippage_abs": round(abs(fill_price - price), 6),
        "slippage_pct": slippage_bps / 10000,
        "raw": {"shadow": True, "simulated_at": time.time()},
    }
    logger.info("shadow_open_simulated",
                asset=asset, direction=direction, size=size,
                fill_price=fill_price, slippage_bps=slippage_bps)
    return result


def simulate_close(asset: str, asset_class: str, direction: str,
                   size: float, entry_price: float = 0) -> dict:
    """Simulate a close execution."""
    price = _get_recent_price(asset)
    slippage_bps = 10 if asset_class == "crypto" else 15

    if direction == "LONG":
        fill_price = price * (1 - slippage_bps / 10000)  # selling
    else:
        fill_price = price * (1 + slippage_bps / 10000)  # buying to close

    result = {
        "platform": f"shadow_{asset_class}",
        "order_id": f"shadow_close_{asset}_{int(time.time())}",
        "fill_price": round(fill_price, 6),
        "fill_qty": size,
        "status": "FILLED",
        "lifecycle": "FILLED",
        "commission": round(size * fill_price * 0.0004, 4),
        "slippage_abs": round(abs(fill_price - price), 6),
        "raw": {"shadow": True},
    }
    logger.info("shadow_close_simulated",
                asset=asset, direction=direction, size=size,
                fill_price=fill_price)
    return result


def _get_recent_price(asset: str) -> float:
    """Get recent price from Redis data cache or last candle."""
    try:
        import redis
        r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
        )
        # Try training position cache first
        import json
        raw = r.get("bahamut:training:positions")
        if raw:
            positions = json.loads(raw)
            for p in positions:
                if p.get("asset") == asset and p.get("current_price", 0) > 0:
                    return float(p["current_price"])
        # Fallback: data cache
        raw = r.get(f"bahamut:data:cache:{asset}:close")
        if raw:
            return float(raw)
    except Exception:
        pass
    # Last resort: return a placeholder (will cause obvious drift)
    logger.warning("shadow_price_unavailable", asset=asset)
    return 1.0
