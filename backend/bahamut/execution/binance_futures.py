"""
Bahamut.AI — Binance Futures Testnet Adapter

For SHORT crypto trades. Spot can't short — Futures can.
Same HMAC signing as Spot, different base URL and endpoints.

Testnet: https://testnet.binancefuture.com
Production: https://fapi.binance.com
"""
import os
import time
import hmac
import hashlib
import httpx
import structlog
from urllib.parse import urlencode

logger = structlog.get_logger()

BASE_URL = os.environ.get("BINANCE_FUTURES_BASE_URL", "https://demo-fapi.binance.com")
API_KEY = os.environ.get("BINANCE_FUTURES_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_FUTURES_API_SECRET", "")

# Same symbol map as spot but with USDT pairs
SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT", "LINKUSD": "LINKUSDT",
    "MATICUSD": "MATICUSDT",
}


def _configured() -> bool:
    return bool(API_KEY and API_SECRET)


def _sign(params: dict) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params)
    signature = hmac.new(
        API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> dict:
    return {"X-MBX-APIKEY": API_KEY}


def _to_symbol(asset: str) -> str:
    return SYMBOL_MAP.get(asset, asset + "USDT")


def get_account() -> dict | None:
    """Get futures account info."""
    if not _configured():
        return None
    try:
        params = _sign({})
        r = httpx.get(f"{BASE_URL}/fapi/v2/account", params=params,
                      headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        logger.error("binance_futures_account_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.error("binance_futures_account_exception", error=str(e))
    return None


def place_market_order(asset: str, side: str, quantity: float) -> dict | None:
    """Place a futures market order. side = 'BUY' or 'SELL'.

    For SHORT: SELL to open, BUY to close.
    For LONG: BUY to open, SELL to close.
    """
    if not _configured():
        logger.warning("binance_futures_not_configured")
        return None

    symbol = _to_symbol(asset)
    params = _sign({
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": _format_qty(asset, quantity),
    })

    try:
        r = httpx.post(f"{BASE_URL}/fapi/v1/order", params=params,
                       headers=_headers(), timeout=10)
        data = r.json()
        if r.status_code == 200:
            fill_price = float(data.get("avgPrice", 0))
            fill_qty = float(data.get("executedQty", quantity))
            logger.info("binance_futures_order_filled",
                        asset=asset, symbol=symbol, side=side,
                        fill_price=fill_price, order_id=data.get("orderId"))
            return {
                "order_id": str(data.get("orderId", "")),
                "fill_price": fill_price,
                "fill_qty": fill_qty,
                "status": data.get("status", "UNKNOWN"),
                "raw": data,
            }
        logger.error("binance_futures_order_error", asset=asset, side=side,
                     status=r.status_code, body=str(data)[:300])
        return {"error": str(data), "status_code": r.status_code}
    except Exception as e:
        logger.error("binance_futures_exception", asset=asset, error=str(e))
        return {"error": str(e)}


def open_short(asset: str, quantity: float) -> dict | None:
    """Open a SHORT position (sell to open)."""
    return place_market_order(asset, "SELL", quantity)


def close_short(asset: str, quantity: float) -> dict | None:
    """Close a SHORT position (buy to close)."""
    return place_market_order(asset, "BUY", quantity)


def open_long(asset: str, quantity: float) -> dict | None:
    """Open a LONG position (buy to open)."""
    return place_market_order(asset, "BUY", quantity)


def close_long(asset: str, quantity: float) -> dict | None:
    """Close a LONG position (sell to close)."""
    return place_market_order(asset, "SELL", quantity)


def get_positions() -> list[dict]:
    """Get all open futures positions."""
    if not _configured():
        return []
    try:
        params = _sign({})
        r = httpx.get(f"{BASE_URL}/fapi/v2/positionRisk", params=params,
                      headers=_headers(), timeout=10)
        if r.status_code == 200:
            positions = []
            for p in r.json():
                amt = float(p.get("positionAmt", 0))
                if abs(amt) > 0:
                    positions.append({
                        "symbol": p.get("symbol", ""),
                        "side": "LONG" if amt > 0 else "SHORT",
                        "qty": abs(amt),
                        "entry_price": float(p.get("entryPrice", 0)),
                        "mark_price": float(p.get("markPrice", 0)),
                        "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                        "leverage": int(p.get("leverage", 1)),
                    })
            return positions
    except Exception as e:
        logger.error("binance_futures_positions_error", error=str(e))
    return []


def _format_qty(asset: str, quantity: float) -> str:
    low_price = {"SHIBUSD", "PEPEUSD", "DOGEUSD", "GALAUSD"}
    if asset in low_price:
        return f"{quantity:.0f}"
    elif asset in {"BTCUSD"}:
        return f"{quantity:.3f}"
    elif asset in {"ETHUSD", "SOLUSD", "BNBUSD"}:
        return f"{quantity:.3f}"
    else:
        return f"{quantity:.2f}"
