"""
Bahamut.AI — Execution Router

Routes trade execution to the correct platform:
  - Crypto → Binance Testnet (spot)
  - Stocks/ETFs → Alpaca Paper Trading
  - Forex/Commodity/Index → Internal only (no broker yet)
"""
import structlog

import json
import os
import time as _time

# ── Redis cache for exchange data ──
_cache: dict[str, tuple[any, float]] = {}
_CACHE_TTL = 300  # 5 minutes (invalidated on trade events)

def _cache_get(key: str):
    """Try Redis first, then in-memory."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        raw = r.get(f"bahamut:exec_cache:{key}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    entry = _cache.get(key)
    if entry and entry[1] > _time.time():
        return entry[0]
    return None

def _cache_set(key: str, data):
    """Write to both Redis and in-memory."""
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.setex(f"bahamut:exec_cache:{key}", _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass
    _cache[key] = (data, _time.time() + _CACHE_TTL)

logger = structlog.get_logger()


def execute_open(asset: str, asset_class: str, direction: str,
                 size: float, risk_amount: float, **kwargs) -> dict:
    """Execute a position open on the appropriate platform."""
    platform = _get_platform(asset, asset_class)

    if platform == "binance":
        return _binance_open(asset, direction, size)
    elif platform == "alpaca":
        return _alpaca_open(asset, direction, size, risk_amount)
    else:
        return {"platform": "internal", "order_id": "", "fill_price": 0,
                "fill_qty": size, "status": "internal"}


def execute_close(asset: str, asset_class: str, direction: str,
                  size: float, entry_price: float, **kwargs) -> dict:
    """Execute a position close on the appropriate platform."""
    platform = _get_platform(asset, asset_class)

    if platform == "binance":
        return _binance_close(asset, direction, size)
    elif platform == "alpaca":
        return _alpaca_close(asset, direction, size)
    else:
        return {"platform": "internal", "order_id": "", "fill_price": 0,
                "fill_qty": size, "status": "internal"}


def get_execution_status() -> dict:
    """Get status of all execution platforms with detailed errors."""
    status = {"binance_spot": "not_configured", "binance_futures": "not_configured", "alpaca": "not_configured"}
    try:
        from bahamut.execution.binance_adapter import get_account, _configured as b_cfg, SPOT_URL, API_KEY as SPOT_KEY
        if b_cfg():
            acc = get_account()
            if acc:
                status["binance_spot"] = "connected"
                status["binance_spot_balances"] = len(acc.get("balances", []))
            else:
                status["binance_spot"] = "error"
                status["binance_spot_url"] = SPOT_URL
                status["binance_spot_key_prefix"] = SPOT_KEY[:8] + "..." if SPOT_KEY else "MISSING"
        else:
            status["binance_spot"] = "not_configured (BINANCE_TESTNET_API_KEY missing)"
    except Exception as e:
        status["binance_spot"] = f"error: {str(e)[:100]}"

    try:
        from bahamut.execution.binance_futures import get_account as fut_acc, _configured as f_cfg, BASE_URL as FUT_URL, API_KEY as FUT_KEY
        if f_cfg():
            acc = fut_acc()
            if acc:
                status["binance_futures"] = "connected"
                status["binance_futures_balance"] = acc.get("totalWalletBalance", "?")
            else:
                status["binance_futures"] = "error"
                status["binance_futures_url"] = FUT_URL
                status["binance_futures_key_prefix"] = FUT_KEY[:8] + "..." if FUT_KEY else "MISSING"
        else:
            status["binance_futures"] = "not_configured (BINANCE_FUTURES_API_KEY missing)"
    except Exception as e:
        status["binance_futures"] = f"error: {str(e)[:100]}"

    try:
        from bahamut.execution.alpaca_adapter import get_account, _configured as a_cfg
        if a_cfg():
            acc = get_account()
            if acc:
                status["alpaca"] = "connected"
                status["alpaca_cash"] = acc.get("cash", 0)
                status["alpaca_equity"] = acc.get("equity", 0)
                status["alpaca_buying_power"] = acc.get("buying_power", 0)
            else:
                status["alpaca"] = "error"
        else:
            status["alpaca"] = "not_configured (ALPACA_API_KEY missing)"
    except Exception as e:
        status["alpaca"] = f"error: {str(e)[:100]}"
    return status


def _get_platform(asset: str, asset_class: str) -> str:
    if asset_class == "crypto":
        from bahamut.execution.binance_futures import _configured
        return "binance" if _configured() else "internal"
    elif asset_class in ("stock",):
        from bahamut.execution.alpaca_adapter import _configured
        return "alpaca" if _configured() else "internal"
    else:
        return "internal"


def _get_crypto_platform(direction: str) -> str:
    """All crypto uses Futures (supports both LONG and SHORT with one key)."""
    from bahamut.execution.binance_futures import _configured as fut_cfg
    return "binance_futures" if fut_cfg() else "internal"


def _binance_open(asset: str, direction: str, size: float) -> dict:
    # ALL crypto → Futures (one key for LONG + SHORT)
    try:
        from bahamut.execution.binance_futures import _configured, place_market_order
        if _configured():
            side = "BUY" if direction == "LONG" else "SELL"
            result = place_market_order(asset, side, size)
            if result and "error" not in result:
                return {"platform": "binance_futures", "order_id": result.get("order_id", ""),
                        "fill_price": result.get("fill_price", 0),
                        "fill_qty": result.get("fill_qty", size), "status": "filled"}
            error = result.get("error", "Unknown") if result else "No response"
            logger.error("binance_futures_open_failed", asset=asset, direction=direction, error=error)
            return {"platform": "binance_futures", "status": "error", "error": str(error)[:200],
                    "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        logger.error("binance_futures_exception", asset=asset, error=str(e)[:100])
    return {"platform": "internal", "order_id": "", "fill_price": 0,
            "fill_qty": size, "status": "internal"}


def _binance_close(asset: str, direction: str, size: float) -> dict:
    # Close: opposite side on Futures
    try:
        from bahamut.execution.binance_futures import _configured, place_market_order
        if _configured():
            side = "SELL" if direction == "LONG" else "BUY"
            result = place_market_order(asset, side, size)
            if result and "error" not in result:
                return {"platform": "binance_futures", "order_id": result.get("order_id", ""),
                        "fill_price": result.get("fill_price", 0),
                        "fill_qty": result.get("fill_qty", size), "status": "filled"}
            error = result.get("error", "Unknown") if result else "No response"
            return {"platform": "binance_futures", "status": "error", "error": str(error)[:200],
                    "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        logger.error("binance_futures_close_exception", asset=asset, error=str(e)[:100])
    return {"platform": "internal", "order_id": "", "fill_price": 0,
            "fill_qty": size, "status": "internal"}


def _alpaca_open(asset: str, direction: str, size: float, risk_amount: float) -> dict:
    from bahamut.execution.alpaca_adapter import place_market_buy, place_market_sell, is_market_open
    if not is_market_open():
        logger.info("alpaca_market_closed", asset=asset, msg="Will fill at next open")
    try:
        result = place_market_buy(asset, quantity=size) if direction == "LONG" else place_market_sell(asset, quantity=size)
        if result and "error" not in result:
            return {"platform": "alpaca", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": result.get("status", "submitted")}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "alpaca", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "alpaca", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


def _alpaca_close(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.alpaca_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_sell(asset, size) if direction == "LONG" else place_market_buy(asset, quantity=size)
        if result and "error" not in result:
            return {"platform": "alpaca", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": result.get("status", "submitted")}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "alpaca", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "alpaca", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


# ═══════════════════════════════════════════
# FastAPI Router (for /api/v1/execution endpoints)
# ═══════════════════════════════════════════
from fastapi import APIRouter
router = APIRouter()


@router.get("/status")
async def execution_status():
    """Get status of connected execution platforms (Binance/Alpaca)."""
    return get_execution_status()


@router.get("/platforms")
async def execution_platforms():
    """Show which platform each asset class routes to."""
    return {
        "crypto": "binance_testnet",
        "stock": "alpaca_paper",
        "forex": "internal",
        "commodity": "internal",
        "index": "internal",
    }


@router.get("/binance/live")
async def binance_live_data():
    """Pull data from Binance Futures Demo + open crypto positions from training engine."""
    cached = _cache_get("binance_live")
    if cached:
        cached["_from_cache"] = True
        return cached

    from bahamut.execution.binance_futures import (
        get_account, get_positions, get_trades, get_orders, _configured, BASE_URL
    )
    from datetime import datetime, timezone

    if not _configured():
        return {"error": "Binance Futures not configured. Set BINANCE_FUTURES_API_KEY."}

    # Pull account + positions in parallel
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_account = pool.submit(get_account)
        f_positions = pool.submit(get_positions)
    account_raw = f_account.result()
    exchange_positions = f_positions.result()

    # Build active symbols from positions + training engine
    active_symbols = set()
    for ep in exchange_positions:
        active_symbols.add(ep.get("symbol", ""))
    training_positions = []
    try:
        from bahamut.training.engine import _load_positions
        from bahamut.execution.binance_futures import _to_symbol
        from dataclasses import asdict
        all_pos = _load_positions()
        for p in all_pos:
            if p.asset_class == "crypto":
                training_positions.append({
                    **asdict(p),
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "source": "training_engine",
                })
                active_symbols.add(_to_symbol(p.asset))
    except Exception:
        pass
    active_symbols.update(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])
    active_list = [s for s in active_symbols if s]

    # Trades + orders in parallel (each internally parallelized too)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_trades = pool.submit(get_trades, active_list, 30)
        f_orders = pool.submit(get_orders, active_list, 10)
    futures_trades = f_trades.result()
    futures_orders = f_orders.result()

    # Account summary
    balance = 0
    unrealized = 0
    if account_raw:
        balance = float(account_raw.get("totalWalletBalance", 0))
        unrealized = float(account_raw.get("totalUnrealizedProfit", 0))

    # Compute PnL from futures trades (realized)
    realized_pnl = sum(t.get("realized_pnl", 0) for t in futures_trades)

    # Group trades by asset for stats
    asset_stats: dict[str, dict] = {}
    for t in futures_trades:
        a = t["asset"]
        if a not in asset_stats:
            asset_stats[a] = {"trades": 0, "realized_pnl": 0, "volume": 0}
        asset_stats[a]["trades"] += 1
        asset_stats[a]["realized_pnl"] = round(asset_stats[a]["realized_pnl"] + t.get("realized_pnl", 0), 2)
        asset_stats[a]["volume"] = round(asset_stats[a]["volume"] + t.get("quote_qty", 0), 2)

    # Count wins/losses from realized PnL
    pnl_trades = [t for t in futures_trades if abs(t.get("realized_pnl", 0)) > 0.01]
    wins = [t for t in pnl_trades if t["realized_pnl"] > 0.01]
    losses = [t for t in pnl_trades if t["realized_pnl"] < -0.01]
    total_trades = len(pnl_trades)
    wr = len(wins) / max(1, total_trades) if total_trades > 0 else 0
    gross_profit = sum(t["realized_pnl"] for t in wins)
    gross_loss = abs(sum(t["realized_pnl"] for t in losses))
    pf = gross_profit / max(0.01, gross_loss)

    result = {
        "platform": "binance_futures",
        "base_url": BASE_URL,
        "connected": True,
        "account": {
            "balance": round(balance, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(balance + unrealized, 2),
        },
        "summary": {
            "total_trades": total_trades,
            "total_fills": len(futures_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr, 4),
            "total_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "combined_pnl": round(realized_pnl + unrealized, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(pf, 2),
            "total_volume": round(sum(s.get("volume", 0) for s in asset_stats.values()), 2),
            "total_commissions": round(sum(t.get("commission", 0) for t in futures_trades), 4),
        },
        "positions": exchange_positions,
        "training_positions": training_positions,
        "by_asset": dict(sorted(asset_stats.items(), key=lambda x: x[1]["realized_pnl"], reverse=True)),
        "trades": futures_trades[:100],
        "raw_orders": futures_orders[:100],
        "raw_fills": futures_trades[:100],
    }
    _cache_set("binance_live", result)
    return result


@router.get("/alpaca/live")
async def alpaca_live_data():
    """Pull all data directly from Alpaca Paper Trading API. Cached 30s."""
    cached = _cache_get("alpaca_live")
    if cached:
        cached["_from_cache"] = True
        return cached

    from bahamut.execution.alpaca_adapter import (
        get_account, get_all_orders, get_all_positions, get_activities,
        get_portfolio_history, _configured
    )

    if not _configured():
        return {"error": "Alpaca not configured. Set ALPACA_API_KEY."}

    # Pull everything from Alpaca IN PARALLEL
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_account = pool.submit(get_account)
        f_orders = pool.submit(get_all_orders, "all")
        f_positions = pool.submit(get_all_positions)
        f_fills = pool.submit(get_activities, "FILL")

    account = f_account.result()
    orders = f_orders.result()
    positions = f_positions.result()
    fills = f_fills.result()

    # Build round-trips from FILLED ORDERS (more reliable than Activities)
    filled_orders = [o for o in orders if o.get("status") == "filled" and o.get("filled_avg_price", 0) > 0]

    asset_buys: dict[str, list] = {}
    asset_sells: dict[str, list] = {}

    # Try fills first, fall back to filled orders
    source_data = fills if fills else filled_orders
    side_key = "side"  # both use "side"

    for f in source_data:
        a = f.get("asset") or f.get("symbol", "")
        side = (f.get(side_key, "") or "").lower()
        price = f.get("price", 0) or f.get("filled_avg_price", 0)
        qty = f.get("qty", 0) or f.get("filled_qty", 0)
        ts = f.get("transaction_time", "") or f.get("filled_at", "") or f.get("created_at", "")

        if not a or not price:
            continue

        entry = {"asset": a, "side": side, "price": float(price), "qty": float(qty), "time": ts}

        if side == "buy":
            asset_buys.setdefault(a, []).append(entry)
        elif side == "sell":
            asset_sells.setdefault(a, []).append(entry)

    round_trips = []
    asset_stats: dict[str, dict] = {}

    all_assets = set(list(asset_buys.keys()) + list(asset_sells.keys()))
    for asset in all_assets:
        buys = sorted(asset_buys.get(asset, []), key=lambda x: x.get("time", ""))
        sells = sorted(asset_sells.get(asset, []), key=lambda x: x.get("time", ""))

        if asset not in asset_stats:
            asset_stats[asset] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}

        for i in range(min(len(buys), len(sells))):
            b = buys[i]
            s = sells[i]
            pnl = (s["price"] - b["price"]) * min(b["qty"], s["qty"])
            rt = {
                "asset": asset,
                "direction": "LONG",
                "entry_price": b["price"],
                "exit_price": s["price"],
                "qty": min(b["qty"], s["qty"]),
                "pnl": round(pnl, 2),
                "entry_time": b.get("time", ""),
                "exit_time": s.get("time", ""),
            }
            round_trips.append(rt)
            asset_stats[asset]["trades"] += 1
            asset_stats[asset]["pnl"] = round(asset_stats[asset]["pnl"] + pnl, 2)
            if pnl > 0.01:
                asset_stats[asset]["wins"] += 1
            elif pnl < -0.01:
                asset_stats[asset]["losses"] += 1

    round_trips.sort(key=lambda x: x.get("exit_time", ""), reverse=True)

    # Summary
    total_pnl = sum(rt["pnl"] for rt in round_trips)
    wins = [rt for rt in round_trips if rt["pnl"] > 0.01]
    losses = [rt for rt in round_trips if rt["pnl"] < -0.01]
    wr = len(wins) / max(1, len(wins) + len(losses))
    gross_profit = sum(rt["pnl"] for rt in wins)
    gross_loss = abs(sum(rt["pnl"] for rt in losses))
    pf = gross_profit / max(0.01, gross_loss)

    unrealized_pnl = sum(p.get("unrealized_pl", 0) for p in positions)

    # Account-level PnL (most accurate — from Alpaca's own accounting)
    starting_capital = 100000  # Alpaca paper starts at $100K
    account_equity = account.get("equity", starting_capital) if account else starting_capital
    account_pnl = round(account_equity - starting_capital, 2)

    result = {
        "platform": "alpaca_paper",
        "connected": True,
        "account": account,
        "positions": positions,
        "summary": {
            "total_trades": len(round_trips),
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(round_trips) - len(wins) - len(losses),
            "win_rate": round(wr, 4),
            "total_pnl": round(account_pnl, 2),
            "realized_pnl": round(total_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "combined_pnl": round(account_pnl, 2),
            "open_positions": len(positions),
            "total_orders": len(filled_orders),
            "total_fills": len(source_data),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(pf, 2),
            "avg_win": round(gross_profit / max(1, len(wins)), 2),
            "avg_loss": round(gross_loss / max(1, len(losses)), 2),
            "best_trade": max(round_trips, key=lambda x: x["pnl"]) if round_trips else None,
            "worst_trade": min(round_trips, key=lambda x: x["pnl"]) if round_trips else None,
        },
        "by_asset": dict(sorted(asset_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)),
        "trades": round_trips,
        "raw_orders": orders[:100],
        "raw_fills": fills[:100],
    }
    _cache_set("alpaca_live", result)
    return result


def invalidate_platform_cache(platform: str):
    """Invalidate cached data after a trade executes. Called from training engine."""
    key = f"{platform}_live"
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.delete(f"bahamut:exec_cache:{key}")
    except Exception:
        pass
    if key in _cache:
        del _cache[key]


@router.get("/test-connections")
async def test_connections():
    """Test all exchange connections with detailed error reporting."""
    results = {}

    # Test Binance Spot
    try:
        from bahamut.execution.binance_adapter import _configured, API_KEY, SPOT_URL
        import httpx
        results["binance_spot"] = {
            "configured": _configured(),
            "url": SPOT_URL,
            "key_set": bool(API_KEY),
            "key_prefix": API_KEY[:12] + "..." if API_KEY else "NOT SET",
        }
        if _configured():
            r = httpx.get(f"{SPOT_URL}/api/v3/time", timeout=5)
            results["binance_spot"]["ping_status"] = r.status_code
            # Test authenticated endpoint
            from bahamut.execution.binance_adapter import get_account
            acc = get_account()
            results["binance_spot"]["auth_ok"] = acc is not None
            if not acc:
                # Try raw request to see error
                import time as _t, hmac as _hmac, hashlib as _hash
                from bahamut.execution.binance_adapter import API_SECRET
                params = {"timestamp": int(_t.time() * 1000)}
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                sig = _hmac.new(API_SECRET.encode(), qs.encode(), _hash.sha256).hexdigest()
                params["signature"] = sig
                r2 = httpx.get(f"{SPOT_URL}/api/v3/account", params=params,
                              headers={"X-MBX-APIKEY": API_KEY}, timeout=5)
                results["binance_spot"]["error_status"] = r2.status_code
                results["binance_spot"]["error_body"] = r2.text[:200]
    except Exception as e:
        results["binance_spot"] = {"error": str(e)[:200]}

    # Test Binance Futures
    try:
        from bahamut.execution.binance_futures import _configured as f_cfg, API_KEY as F_KEY, BASE_URL as F_URL
        import httpx
        results["binance_futures"] = {
            "configured": f_cfg(),
            "url": F_URL,
            "key_set": bool(F_KEY),
            "key_prefix": F_KEY[:12] + "..." if F_KEY else "NOT SET",
        }
        if f_cfg():
            r = httpx.get(f"{F_URL}/fapi/v1/time", timeout=5)
            results["binance_futures"]["ping_status"] = r.status_code
            from bahamut.execution.binance_futures import get_account as fut_acc
            acc = fut_acc()
            results["binance_futures"]["auth_ok"] = acc is not None
            if not acc:
                from bahamut.execution.binance_futures import API_SECRET as F_SECRET
                import time as _t, hmac as _hmac, hashlib as _hash
                params = {"timestamp": int(_t.time() * 1000)}
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                sig = _hmac.new(F_SECRET.encode(), qs.encode(), _hash.sha256).hexdigest()
                params["signature"] = sig
                r2 = httpx.get(f"{F_URL}/fapi/v2/account", params=params,
                              headers={"X-MBX-APIKEY": F_KEY}, timeout=5)
                results["binance_futures"]["error_status"] = r2.status_code
                results["binance_futures"]["error_body"] = r2.text[:200]
    except Exception as e:
        results["binance_futures"] = {"error": str(e)[:200]}

    # Test Alpaca
    try:
        from bahamut.execution.alpaca_adapter import _configured as a_cfg, API_KEY as A_KEY, BASE_URL as A_URL
        import httpx
        results["alpaca"] = {
            "configured": a_cfg(),
            "url": A_URL,
            "key_prefix": A_KEY[:12] + "..." if A_KEY else "NOT SET",
        }
        if a_cfg():
            from bahamut.execution.alpaca_adapter import get_account
            acc = get_account()
            results["alpaca"]["auth_ok"] = acc is not None
            if acc:
                results["alpaca"]["equity"] = acc.get("equity")
                results["alpaca"]["cash"] = acc.get("cash")
                results["alpaca"]["buying_power"] = acc.get("buying_power")
                results["alpaca"]["status"] = acc.get("status")
    except Exception as e:
        results["alpaca"] = {"error": str(e)[:200]}

    return results
