"""
Bahamut.AI — Binance Testnet Execution Adapter

Executes crypto trades on Binance Spot Testnet.
Same API as production — just swap keys + base URL to go live.

Testnet base: https://testnet.binance.vision
Production:   https://api.binance.com
"""
import os
import time
import hmac
import hashlib
import httpx
import structlog
from urllib.parse import urlencode

logger = structlog.get_logger()

BASE_URL = os.environ.get("BINANCE_BASE_URL", "https://testnet.binance.vision")
API_KEY = os.environ.get("BINANCE_TESTNET_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_TESTNET_API_SECRET", "")

# Bahamut symbol → Binance symbol map
SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT", "DOTUSD": "DOTUSDT",
    "LINKUSD": "LINKUSDT", "MATICUSD": "MATICUSDT", "SHIBUSD": "SHIBUSDT",
    "TONUSD": "TONUSDT", "NEARUSD": "NEARUSDT", "SUIUSD": "SUIUSDT",
    "PEPEUSD": "PEPEUSDT", "TRXUSD": "TRXUSDT", "LTCUSD": "LTCUSDT",
    "BCHUSD": "BCHUSDT", "XLMUSD": "XLMUSDT", "UNIUSD": "UNIUSDT",
    "ICPUSD": "ICPUSDT", "HBARUSD": "HBARUSDT", "FILUSD": "FILUSDT",
    "APTUSD": "APTUSDT", "ARBUSD": "ARBUSDT", "OPUSD": "OPUSDT",
    "MKRUSD": "MKRUSDT", "AAVEUSD": "AAVEUSDT", "ATOMUSD": "ATOMUSDT",
    "ALGOUSD": "ALGOUSDT", "VETUSD": "VETUSDT", "FTMUSD": "FTMUSDT",
    "SANDUSD": "SANDUSDT", "MANAUSD": "MANAUSDT", "AXSUSD": "AXSUSDT",
    "GALAUSD": "GALAUSDT", "ENSUSD": "ENSUSDT", "LDOUSD": "LDOUSDT",
    "RENDERUSD": "RENDERUSDT", "INJUSD": "INJUSDT",
}


def _configured() -> bool:
    return bool(API_KEY and API_SECRET)


def _sign(params: dict) -> dict:
    """Add timestamp and HMAC signature to params."""
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params)
    signature = hmac.new(
        API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> dict:
    return {"X-MBX-APIKEY": API_KEY}


def _to_binance_symbol(asset: str) -> str:
    return SYMBOL_MAP.get(asset, asset + "USDT")


def get_account() -> dict | None:
    """Get testnet account info (balances)."""
    if not _configured():
        return None
    try:
        params = _sign({})
        r = httpx.get(f"{BASE_URL}/api/v3/account", params=params,
                      headers=_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        logger.error("binance_account_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.error("binance_account_exception", error=str(e))
    return None


def place_market_buy(asset: str, quantity: float) -> dict | None:
    """Place a market buy order. Returns order result with fill price."""
    if not _configured():
        logger.warning("binance_not_configured")
        return None

    symbol = _to_binance_symbol(asset)
    params = _sign({
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": _format_qty(asset, quantity),
    })

    try:
        r = httpx.post(f"{BASE_URL}/api/v3/order", params=params,
                       headers=_headers(), timeout=10)
        data = r.json()
        if r.status_code == 200:
            fill_price = _avg_fill_price(data)
            fill_qty = float(data.get("executedQty", quantity))
            logger.info("binance_buy_filled",
                        asset=asset, symbol=symbol, qty=fill_qty,
                        fill_price=fill_price, order_id=data.get("orderId"))
            return {
                "order_id": str(data.get("orderId", "")),
                "fill_price": fill_price,
                "fill_qty": fill_qty,
                "status": data.get("status", "UNKNOWN"),
                "raw": data,
            }
        logger.error("binance_buy_error", asset=asset, status=r.status_code,
                     body=str(data)[:300])
        return {"error": str(data), "status_code": r.status_code}
    except Exception as e:
        logger.error("binance_buy_exception", asset=asset, error=str(e))
        return {"error": str(e)}


def place_market_sell(asset: str, quantity: float) -> dict | None:
    """Place a market sell order. Returns order result with fill price."""
    if not _configured():
        return None

    symbol = _to_binance_symbol(asset)
    params = _sign({
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": _format_qty(asset, quantity),
    })

    try:
        r = httpx.post(f"{BASE_URL}/api/v3/order", params=params,
                       headers=_headers(), timeout=10)
        data = r.json()
        if r.status_code == 200:
            fill_price = _avg_fill_price(data)
            fill_qty = float(data.get("executedQty", quantity))
            logger.info("binance_sell_filled",
                        asset=asset, symbol=symbol, qty=fill_qty,
                        fill_price=fill_price, order_id=data.get("orderId"))
            return {
                "order_id": str(data.get("orderId", "")),
                "fill_price": fill_price,
                "fill_qty": fill_qty,
                "status": data.get("status", "UNKNOWN"),
                "raw": data,
            }
        logger.error("binance_sell_error", asset=asset, status=r.status_code,
                     body=str(data)[:300])
        return {"error": str(data), "status_code": r.status_code}
    except Exception as e:
        logger.error("binance_sell_exception", asset=asset, error=str(e))
        return {"error": str(e)}


def get_price(asset: str) -> float | None:
    """Get current price from Binance."""
    symbol = _to_binance_symbol(asset)
    try:
        r = httpx.get(f"{BASE_URL}/api/v3/ticker/price",
                      params={"symbol": symbol}, timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    return None


def _avg_fill_price(order: dict) -> float:
    """Calculate average fill price from order fills."""
    fills = order.get("fills", [])
    if not fills:
        return float(order.get("price", 0))
    total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
    total_qty = sum(float(f["qty"]) for f in fills)
    return round(total_cost / max(total_qty, 1e-10), 8)


def _format_qty(asset: str, quantity: float) -> str:
    """Format quantity to Binance precision rules."""
    # BTC: 5 decimals, most alts: 2-3, SHIB/PEPE: 0
    low_price = {"SHIBUSD", "PEPEUSD", "DOGEUSD", "GALAUSD"}
    if asset in low_price:
        return f"{quantity:.0f}"
    elif asset in {"BTCUSD"}:
        return f"{quantity:.5f}"
    elif asset in {"ETHUSD", "SOLUSD", "BNBUSD", "LTCUSD", "BCHUSD", "MKRUSD"}:
        return f"{quantity:.4f}"
    else:
        return f"{quantity:.2f}"
