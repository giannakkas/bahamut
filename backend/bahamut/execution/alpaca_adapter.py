"""
Bahamut.AI — Alpaca Paper Trading Execution Adapter

Executes stock/ETF trades on Alpaca Paper Trading.
Same API as production — just swap keys + base URL to go live.

Paper base:     https://paper-api.alpaca.markets
Production:     https://api.alpaca.markets
"""
import os
import time
import httpx
import structlog

logger = structlog.get_logger()

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"

API_KEY = os.environ.get("ALPACA_API_KEY", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "")
IS_PAPER = os.environ.get("ALPACA_PAPER", "true").lower() == "true"

BASE_URL = PAPER_URL if IS_PAPER else LIVE_URL

# Assets supported on Alpaca (stocks + ETFs)
SUPPORTED_ASSETS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
    "NFLX", "COIN", "SPY", "QQQ", "JPM", "BAC", "GS",
    "CRM", "ORCL", "UBER", "SQ", "SHOP",
}


def _configured() -> bool:
    return bool(API_KEY and API_SECRET)


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
        "Content-Type": "application/json",
    }


def get_account() -> dict | None:
    """Get paper trading account info (cash, equity, buying power)."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{BASE_URL}/v2/account", headers=_headers(), timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "cash": float(data.get("cash", 0)),
                "equity": float(data.get("equity", 0)),
                "buying_power": float(data.get("buying_power", 0)),
                "portfolio_value": float(data.get("portfolio_value", 0)),
                "status": data.get("status", ""),
            }
        logger.error("alpaca_account_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.error("alpaca_account_exception", error=str(e))
    return None


def place_market_buy(asset: str, quantity: float = None, notional: float = None,
                     client_order_id: str = "") -> dict | None:
    """Place a market buy order.

    Args:
        asset: Stock symbol (e.g. AAPL, NFLX)
        quantity: Number of shares (fractional OK)
        notional: Dollar amount to buy (alternative to quantity)
        client_order_id: Idempotency key for dedup/retry safety
    """
    if not _configured():
        logger.warning("alpaca_not_configured")
        return None

    if asset not in SUPPORTED_ASSETS:
        logger.warning("alpaca_unsupported_asset", asset=asset)
        return None

    order = {
        "symbol": asset,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "client_order_id": client_order_id or f"bah_{asset.lower()}_{int(time.time()*1000)}",
    }

    if notional:
        order["notional"] = round(notional, 2)
    elif quantity:
        order["qty"] = str(round(quantity, 6))
    else:
        return {"error": "Must provide quantity or notional"}

    try:
        _t0 = time.time()
        r = httpx.post(f"{BASE_URL}/v2/orders", json=order,
                       headers=_headers(), timeout=5)
        try:
            from bahamut.execution._latency import record as _rec_latency
            _rec_latency("alpaca", (time.time() - _t0) * 1000)
        except Exception:
            pass
        data = r.json()
        if r.status_code in (200, 201):
            logger.info("alpaca_buy_submitted",
                        asset=asset, order_id=data.get("id"),
                        status=data.get("status"))
            # Alpaca fills async — poll for fill
            fill = _wait_for_fill(data.get("id"))
            if fill:
                return fill
            return {
                "order_id": data.get("id", ""),
                "fill_price": float(data.get("filled_avg_price") or 0),
                "fill_qty": float(data.get("filled_qty") or 0),
                "status": data.get("status", ""),
                "raw": data,
            }
        logger.error("alpaca_buy_error", asset=asset, status=r.status_code,
                     body=str(data)[:300])
        return {"error": str(data), "status_code": r.status_code}
    except Exception as e:
        logger.error("alpaca_buy_exception", asset=asset, error=str(e))
        return {"error": str(e)}


def place_market_sell(asset: str, quantity: float,
                      client_order_id: str = "") -> dict | None:
    """Place a market sell order."""
    if not _configured():
        return None

    if asset not in SUPPORTED_ASSETS:
        return {"error": f"Unsupported asset: {asset}"}

    order = {
        "symbol": asset,
        "side": "sell",
        "type": "market",
        "time_in_force": "day",
        "qty": str(round(quantity, 6)),
        "client_order_id": client_order_id or f"bah_{asset.lower()}_{int(time.time()*1000)}",
    }

    try:
        _t0 = time.time()
        r = httpx.post(f"{BASE_URL}/v2/orders", json=order,
                       headers=_headers(), timeout=5)
        try:
            from bahamut.execution._latency import record as _rec_latency
            _rec_latency("alpaca", (time.time() - _t0) * 1000)
        except Exception:
            pass
        data = r.json()
        if r.status_code in (200, 201):
            logger.info("alpaca_sell_submitted",
                        asset=asset, order_id=data.get("id"),
                        status=data.get("status"))
            fill = _wait_for_fill(data.get("id"))
            if fill:
                return fill
            return {
                "order_id": data.get("id", ""),
                "fill_price": float(data.get("filled_avg_price") or 0),
                "fill_qty": float(data.get("filled_qty") or 0),
                "status": data.get("status", ""),
                "raw": data,
            }
        logger.error("alpaca_sell_error", asset=asset, status=r.status_code,
                     body=str(data)[:300])
        return {"error": str(data), "status_code": r.status_code}
    except Exception as e:
        logger.error("alpaca_sell_exception", asset=asset, error=str(e))
        return {"error": str(e)}


def get_position(asset: str) -> dict | None:
    """Get current position for an asset on Alpaca."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{BASE_URL}/v2/positions/{asset}",
                      headers=_headers(), timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "qty": float(data.get("qty", 0)),
                "avg_entry": float(data.get("avg_entry_price", 0)),
                "market_value": float(data.get("market_value", 0)),
                "unrealized_pnl": float(data.get("unrealized_pl", 0)),
                "current_price": float(data.get("current_price", 0)),
            }
        elif r.status_code == 404:
            return None  # No position
    except Exception:
        pass
    return None


def get_price(asset: str) -> float | None:
    """Get latest price from Alpaca market data."""
    if not _configured():
        return None
    try:
        # Use data API for latest trade
        data_url = "https://data.alpaca.markets" if not IS_PAPER else "https://data.alpaca.markets"
        r = httpx.get(f"{data_url}/v2/stocks/{asset}/trades/latest",
                      headers=_headers(), timeout=5)
        if r.status_code == 200:
            return float(r.json().get("trade", {}).get("p", 0))
    except Exception:
        pass
    return None


def is_market_open() -> bool:
    """Check if US stock market is currently open."""
    if not _configured():
        return False
    try:
        r = httpx.get(f"{BASE_URL}/v2/clock", headers=_headers(), timeout=5)
        if r.status_code == 200:
            return r.json().get("is_open", False)
    except Exception:
        pass
    return False


def _wait_for_fill(order_id: str, max_wait: int = 5) -> dict | None:
    """Poll for order fill (market orders fill almost instantly)."""
    if not order_id:
        return None
    import time
    for _ in range(max_wait):
        time.sleep(1)
        try:
            r = httpx.get(f"{BASE_URL}/v2/orders/{order_id}",
                          headers=_headers(), timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "filled":
                    return {
                        "order_id": data.get("id", ""),
                        "fill_price": float(data.get("filled_avg_price") or 0),
                        "fill_qty": float(data.get("filled_qty") or 0),
                        "status": "filled",
                        "raw": data,
                    }
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════
# HISTORY — Pull trades directly from Alpaca
# ═══════════════════════════════════════════

def get_all_orders(status: str = "all", limit: int = 500) -> list[dict]:
    """Fetch all orders from Alpaca paper trading."""
    if not _configured():
        return []
    try:
        params = {"status": status, "limit": limit, "direction": "desc"}
        r = httpx.get(f"{BASE_URL}/v2/orders", params=params,
                      headers=_headers(), timeout=15)
        if r.status_code == 200:
            orders = []
            for o in r.json():
                orders.append({
                    "order_id": o.get("id", ""),
                    "asset": o.get("symbol", ""),
                    "side": o.get("side", "").upper(),
                    "type": o.get("type", ""),
                    "status": o.get("status", ""),
                    "qty": float(o.get("qty") or o.get("filled_qty") or 0),
                    "filled_qty": float(o.get("filled_qty") or 0),
                    "filled_avg_price": float(o.get("filled_avg_price") or 0),
                    "submitted_at": o.get("submitted_at", ""),
                    "filled_at": o.get("filled_at", ""),
                    "created_at": o.get("created_at", ""),
                })
            return orders
        logger.error("alpaca_orders_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.error("alpaca_orders_exception", error=str(e))
    return []


def get_all_positions() -> list[dict]:
    """Fetch all open positions from Alpaca."""
    if not _configured():
        return []
    try:
        r = httpx.get(f"{BASE_URL}/v2/positions", headers=_headers(), timeout=5)
        if r.status_code == 200:
            positions = []
            for p in r.json():
                positions.append({
                    "asset": p.get("symbol", ""),
                    "qty": float(p.get("qty", 0)),
                    "side": p.get("side", ""),
                    "avg_entry_price": float(p.get("avg_entry_price", 0)),
                    "current_price": float(p.get("current_price", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "cost_basis": float(p.get("cost_basis", 0)),
                    "unrealized_pl": float(p.get("unrealized_pl", 0)),
                    "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
                    "change_today": float(p.get("change_today", 0)),
                })
            return positions
    except Exception as e:
        logger.error("alpaca_positions_exception", error=str(e))
    return []


def get_activities(activity_type: str = "FILL", limit: int = 500) -> list[dict]:
    """Fetch account activities (fills, dividends, etc.) from Alpaca."""
    if not _configured():
        return []
    try:
        params = {"activity_type": activity_type, "page_size": limit, "direction": "desc"}
        r = httpx.get(f"{BASE_URL}/v2/account/activities/{activity_type}",
                      params=params, headers=_headers(), timeout=15)
        if r.status_code == 200:
            activities = []
            for a in r.json():
                activities.append({
                    "id": a.get("id", ""),
                    "activity_type": a.get("activity_type", ""),
                    "asset": a.get("symbol", ""),
                    "side": a.get("side", ""),
                    "qty": float(a.get("qty", 0)),
                    "price": float(a.get("price", 0)),
                    "cum_qty": float(a.get("cum_qty") or a.get("qty") or 0),
                    "order_id": a.get("order_id", ""),
                    "transaction_time": a.get("transaction_time", ""),
                    "type": a.get("type", ""),
                })
            return activities
    except Exception as e:
        logger.error("alpaca_activities_exception", error=str(e))
    return []


def get_portfolio_history(period: str = "1M") -> dict | None:
    """Fetch portfolio history from Alpaca."""
    if not _configured():
        return None
    try:
        params = {"period": period, "timeframe": "1D"}
        r = httpx.get(f"{BASE_URL}/v2/account/portfolio/history",
                      params=params, headers=_headers(), timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None
