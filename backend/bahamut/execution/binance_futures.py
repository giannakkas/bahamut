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
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT", "LINKUSD": "LINKUSDT",
    "MATICUSD": "MATICUSDT", "DOTUSD": "DOTUSDT", "ATOMUSD": "ATOMUSDT",
    "UNIUSD": "UNIUSDT", "LTCUSD": "LTCUSDT", "NEARUSD": "NEARUSDT",
    "ARBUSD": "ARBUSDT", "OPUSD": "OPUSDT", "FILUSD": "FILUSDT",
    "APTUSD": "APTUSDT", "INJUSD": "INJUSDT", "PEPEUSD": "PEPEUSDT",
    "WIFUSD": "WIFUSDT", "RNDRUSD": "RENDERUSDT", "FETUSD": "FETUSDT",
    "TIAUSD": "TIAUSDT", "SUIUSD": "SUIUSDT", "SEIUSD": "SEIUSDT",
    "JUPUSD": "JUPUSDT", "WUSD": "WUSDT", "ENAUSD": "ENAUSDT",
}


def _configured() -> bool:
    return bool(API_KEY and API_SECRET)


def _sign(params: dict) -> dict:
    params["recvWindow"] = 5000
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
                      headers=_headers(), timeout=5)
        if r.status_code == 200:
            return r.json()
        logger.error("binance_futures_account_error", status=r.status_code, body=r.text[:200])
    except Exception as e:
        logger.error("binance_futures_account_exception", error=str(e))
    return None


def place_market_order(asset: str, side: str, quantity: float,
                      client_order_id: str = "",
                      reduce_only: bool = False) -> dict | None:
    """Place a futures market order. side = 'BUY' or 'SELL'.

    For SHORT: SELL to open, BUY to close.
    For LONG: BUY to open, SELL to close.

    Phase 2 Item 6: validates order locally against exchange filters
    before submission. Rejected orders return an error dict rather than
    hitting the network and getting rejected by Binance.
    """
    if not _configured():
        logger.warning("binance_futures_not_configured")
        return None

    symbol = _to_symbol(asset)

    # Phase 2 Item 6: local validation using exchange filters.
    # Validates AFTER rounding (use same formatted qty) — we check the
    # actual qty we're about to submit.
    formatted_qty = _format_qty(asset, quantity)
    if formatted_qty == "INVALID_BELOW_STEP":
        return {
            "error": f"qty_below_step_size",
            "raw_qty": quantity,
            "symbol": symbol,
            "pre_submit_rejected": True,
        }
    try:
        from bahamut.execution.exchange_filters import validate_order
        # Get reference price for notional check
        ref_price = 0.0
        try:
            from bahamut.data.binance_data import get_price
            ref_price = float(get_price(asset) or 0.0)
        except Exception:
            pass
        valid, reason = validate_order(symbol, float(formatted_qty), ref_price)
        if not valid:
            logger.warning("binance_order_pre_submit_rejected",
                           asset=asset, symbol=symbol, qty=formatted_qty,
                           ref_price=ref_price, reason=reason)
            return {
                "error": f"pre_submit_rejected: {reason}",
                "raw_qty": quantity,
                "rounded_qty": float(formatted_qty),
                "symbol": symbol,
                "pre_submit_rejected": True,
            }
    except Exception as e:
        logger.debug("binance_pre_submit_validation_skipped",
                     asset=asset, error=str(e)[:100])

    order_params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": formatted_qty,
        "newClientOrderId": client_order_id or f"bah_{asset.lower()}_{int(time.time()*1000)}",
    }
    if reduce_only:
        order_params["reduceOnly"] = "true"
    params = _sign(order_params)

    try:
        _t0 = time.time()
        r = httpx.post(f"{BASE_URL}/fapi/v1/order", params=params,
                       headers=_headers(), timeout=5)
        try:
            from bahamut.execution._latency import record as _rec_latency
            _rec_latency("binance", (time.time() - _t0) * 1000)
        except Exception:
            pass
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
    return place_market_order(asset, "BUY", quantity, reduce_only=True)


def open_long(asset: str, quantity: float) -> dict | None:
    """Open a LONG position (buy to open)."""
    return place_market_order(asset, "BUY", quantity)


def close_long(asset: str, quantity: float) -> dict | None:
    """Close a LONG position (sell to close)."""
    return place_market_order(asset, "SELL", quantity, reduce_only=True)


def cancel_order(symbol: str, order_id: str) -> dict | None:
    """Cancel a single order on Binance Futures by orderId."""
    if not _configured():
        return None
    try:
        params = _sign({"symbol": symbol, "orderId": order_id})
        r = httpx.delete(f"{BASE_URL}/fapi/v1/order", params=params,
                         headers=_headers(), timeout=5)
        data = r.json()
        if r.status_code == 200:
            logger.info("binance_order_cancelled", symbol=symbol, order_id=order_id)
            return data
        logger.warning("binance_cancel_failed", symbol=symbol,
                       order_id=order_id, status=r.status_code,
                       body=str(data)[:200])
        return {"error": str(data)}
    except Exception as e:
        logger.warning("binance_cancel_exception", symbol=symbol,
                       order_id=order_id, error=str(e)[:100])
        return {"error": str(e)}


def place_bracket_orders(asset: str, side: str, quantity: float,
                         sl_price: float, tp_price: float,
                         entry_client_order_id: str) -> dict:
    """Place SL + TP orders on Binance Futures as broker-side brackets.

    After a market fill, places:
      - STOP_MARKET at sl_price with reduceOnly (stop-loss)
      - TAKE_PROFIT_MARKET at tp_price with reduceOnly (take-profit)

    Both use closePosition=true so they close the entire position.
    Both use MARK_PRICE to avoid wicks triggering on last price.

    Returns dict with 'sl_order' and 'tp_order' containing broker responses.
    """
    if not _configured():
        return {"sl_order": {"error": "not_configured"},
                "tp_order": {"error": "not_configured"}}

    close_side = "SELL" if side == "BUY" else "BUY"
    symbol = _to_symbol(asset)

    result = {"sl_order": {}, "tp_order": {}}

    # Stop-loss
    try:
        sl_params = _sign({
            "symbol": symbol, "side": close_side, "type": "STOP_MARKET",
            "stopPrice": f"{sl_price:.6f}", "closePosition": "true",
            "reduceOnly": "true", "workingType": "MARK_PRICE",
            "newClientOrderId": f"{entry_client_order_id}_sl",
        })
        sl_resp = httpx.post(f"{BASE_URL}/fapi/v1/order", params=sl_params,
                             headers=_headers(), timeout=10)
        result["sl_order"] = sl_resp.json()
        if sl_resp.status_code != 200:
            logger.error("binance_bracket_sl_failed", asset=asset,
                         status=sl_resp.status_code,
                         body=str(result["sl_order"])[:200])
            try:
                from bahamut.monitoring.telegram import send_alert
                send_alert(f"⚠️ BRACKET SL FAILED: {asset} {close_side} "
                           f"sl={sl_price} — position is UNPROTECTED at broker level. "
                           f"Relying on client-side SL only.")
            except Exception:
                pass
    except Exception as e:
        result["sl_order"] = {"error": str(e)[:200]}
        logger.error("binance_bracket_sl_exception", asset=asset, error=str(e)[:100])
        try:
            from bahamut.monitoring.telegram import send_alert
            send_alert(f"⚠️ BRACKET SL EXCEPTION: {asset} — {str(e)[:100]}. "
                       f"Position is UNPROTECTED at broker level.")
        except Exception:
            pass

    # Take-profit
    try:
        tp_params = _sign({
            "symbol": symbol, "side": close_side, "type": "TAKE_PROFIT_MARKET",
            "stopPrice": f"{tp_price:.6f}", "closePosition": "true",
            "reduceOnly": "true", "workingType": "MARK_PRICE",
            "newClientOrderId": f"{entry_client_order_id}_tp",
        })
        tp_resp = httpx.post(f"{BASE_URL}/fapi/v1/order", params=tp_params,
                             headers=_headers(), timeout=10)
        result["tp_order"] = tp_resp.json()
        if tp_resp.status_code != 200:
            logger.error("binance_bracket_tp_failed", asset=asset,
                         status=tp_resp.status_code,
                         body=str(result["tp_order"])[:200])
            try:
                from bahamut.monitoring.telegram import send_alert
                send_alert(f"⚠️ BRACKET TP FAILED: {asset} {close_side} "
                           f"tp={tp_price} — position has no broker-side take-profit.")
            except Exception:
                pass
    except Exception as e:
        result["tp_order"] = {"error": str(e)[:200]}
        logger.error("binance_bracket_tp_exception", asset=asset, error=str(e)[:100])
        try:
            from bahamut.monitoring.telegram import send_alert
            send_alert(f"⚠️ BRACKET TP EXCEPTION: {asset} — {str(e)[:100]}. "
                       f"Position has no broker-side take-profit.")
        except Exception:
            pass

    return result


def get_positions() -> list[dict]:
    """Get all open futures positions."""
    if not _configured():
        return []
    try:
        params = _sign({})
        r = httpx.get(f"{BASE_URL}/fapi/v2/positionRisk", params=params,
                      headers=_headers(), timeout=5)
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
    """Format quantity according to exchange stepSize/precision.

    Phase 2 Item 6: delegates to exchange_filters.format_qty_canonical which
    uses /fapi/v1/exchangeInfo (cached 24h) for real stepSize/minQty.
    Falls back to a hardcoded table if exchangeInfo is unreachable.
    Logs adjustments so raw-vs-rounded is auditable.
    """
    try:
        from bahamut.execution.exchange_filters import format_qty_canonical
        formatted, adj = format_qty_canonical(asset, quantity)
        # Log only when an actual adjustment happened or on error
        if adj.get("error"):
            logger.error("qty_format_invalid",
                         asset=asset, raw_qty=quantity,
                         symbol=adj["symbol"], stepSize=adj["stepSize"],
                         error=adj["error"])
        elif abs(adj["adjustment_delta"]) > 1e-10:
            logger.info("qty_format_adjusted",
                        asset=asset, raw=quantity, rounded=adj["rounded_qty"],
                        stepSize=adj["stepSize"],
                        source=adj["source"])
        return formatted
    except Exception as e:
        # Last-resort fallback — preserve old behavior on any exception
        logger.warning("qty_format_exception", asset=asset, error=str(e)[:100])
        low_price = {"SHIBUSD", "PEPEUSD", "DOGEUSD", "GALAUSD"}
        if asset in low_price:
            return f"{quantity:.0f}"
        elif asset in {"BTCUSD"}:
            return f"{quantity:.3f}"
        elif asset in {"ETHUSD", "SOLUSD", "BNBUSD"}:
            return f"{quantity:.3f}"
        else:
            return f"{quantity:.2f}"


# Reverse symbol map for display
_REVERSE_MAP = {v: k for k, v in SYMBOL_MAP.items()}


def _fetch_symbol_trades(sym: str, limit: int) -> list[dict]:
    """Fetch trades for a single symbol."""
    try:
        params = _sign({"symbol": sym, "limit": limit})
        r = httpx.get(f"{BASE_URL}/fapi/v1/userTrades", params=params,
                      headers=_headers(), timeout=5)
        if r.status_code == 200:
            return [{
                "symbol": sym, "asset": _REVERSE_MAP.get(sym, sym),
                "side": t.get("side", ""), "price": float(t.get("price", 0)),
                "qty": float(t.get("qty", 0)), "quote_qty": float(t.get("quoteQty", 0)),
                "commission": float(t.get("commission", 0)),
                "realized_pnl": float(t.get("realizedPnl", 0)),
                "time": t.get("time", 0), "order_id": t.get("orderId"),
            } for t in r.json()]
    except Exception:
        pass
    return []


def _fetch_symbol_orders(sym: str, limit: int) -> list[dict]:
    """Fetch orders for a single symbol."""
    try:
        params = _sign({"symbol": sym, "limit": limit})
        r = httpx.get(f"{BASE_URL}/fapi/v1/allOrders", params=params,
                      headers=_headers(), timeout=5)
        if r.status_code == 200:
            return [{
                "symbol": sym, "asset": _REVERSE_MAP.get(sym, sym),
                "side": o.get("side", ""), "type": o.get("type", ""),
                "status": o.get("status", ""), "price": float(o.get("price", 0)),
                "avg_price": float(o.get("avgPrice", 0)),
                "qty": float(o.get("origQty", 0)),
                "filled_qty": float(o.get("executedQty", 0)),
                "time": o.get("time", 0), "order_id": o.get("orderId"),
            } for o in r.json()]
    except Exception:
        pass
    return []


def get_trades(symbols: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Get recent account trades from Futures — parallel fetch."""
    if not _configured():
        return []
    if symbols is None:
        symbols = list(SYMBOL_MAP.values())[:5]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = pool.map(lambda s: _fetch_symbol_trades(s, limit), symbols)
    all_trades = [t for batch in results for t in batch]
    all_trades.sort(key=lambda x: x.get("time", 0), reverse=True)
    return all_trades


def get_orders(symbols: list[str] | None = None, limit: int = 20) -> list[dict]:
    """Get recent orders from Futures — parallel fetch."""
    if not _configured():
        return []
    if symbols is None:
        symbols = list(SYMBOL_MAP.values())[:5]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = pool.map(lambda s: _fetch_symbol_orders(s, limit), symbols)
    all_orders = [o for batch in results for o in batch]
    all_orders.sort(key=lambda x: x.get("time", 0), reverse=True)
    return all_orders
