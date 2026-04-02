"""
Bahamut.AI — Execution Router

Routes trade execution to the correct platform:
  - Crypto → Binance Testnet (spot)
  - Stocks/ETFs → Alpaca Paper Trading
  - Forex/Commodity/Index → Internal only (no broker yet)
"""
import structlog

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
    """Get status of both execution platforms."""
    status = {"binance": "not_configured", "alpaca": "not_configured"}
    try:
        from bahamut.execution.binance_adapter import get_account
        from bahamut.execution.binance_adapter import _configured as b_cfg
        if b_cfg():
            acc = get_account()
            status["binance"] = "connected" if acc else "error"
    except Exception as e:
        status["binance"] = f"error: {str(e)[:50]}"
    try:
        from bahamut.execution.alpaca_adapter import get_account
        from bahamut.execution.alpaca_adapter import _configured as a_cfg
        if a_cfg():
            acc = get_account()
            if acc:
                status["alpaca"] = "connected"
                status["alpaca_cash"] = acc.get("cash", 0)
                status["alpaca_equity"] = acc.get("equity", 0)
            else:
                status["alpaca"] = "error"
    except Exception as e:
        status["alpaca"] = f"error: {str(e)[:50]}"
    return status


def _get_platform(asset: str, asset_class: str) -> str:
    if asset_class == "crypto":
        from bahamut.execution.binance_adapter import _configured
        return "binance" if _configured() else "internal"
    elif asset_class in ("stock",):
        from bahamut.execution.alpaca_adapter import _configured
        return "alpaca" if _configured() else "internal"
    else:
        return "internal"


def _binance_open(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.binance_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_buy(asset, size) if direction == "LONG" else place_market_sell(asset, size)
        if result and "error" not in result:
            return {"platform": "binance", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": "filled"}
        error = result.get("error", "Unknown") if result else "No response"
        logger.error("binance_open_failed", asset=asset, error=error)
        return {"platform": "binance", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "binance", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


def _binance_close(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.binance_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_sell(asset, size) if direction == "LONG" else place_market_buy(asset, size)
        if result and "error" not in result:
            return {"platform": "binance", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": "filled"}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "binance", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "binance", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


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
    """Pull all data directly from Binance Testnet API."""
    from bahamut.execution.binance_adapter import (
        get_account, get_all_trades, get_all_orders, get_balances, _configured
    )
    from datetime import datetime, timezone

    if not _configured():
        return {"error": "Binance not configured. Set BINANCE_TESTNET_API_KEY."}

    # Pull everything from Binance
    balances = get_balances()
    trades = get_all_trades()
    orders = get_all_orders()

    # Pair buy/sell trades to compute PnL per round-trip
    # Group trades by asset, pair BUY→SELL sequences
    asset_trades: dict[str, list] = {}
    for t in trades:
        a = t["asset"]
        if a not in asset_trades:
            asset_trades[a] = []
        asset_trades[a].append(t)

    round_trips = []
    asset_stats: dict[str, dict] = {}

    for asset, at in asset_trades.items():
        # Sort by time ascending for pairing
        at.sort(key=lambda x: x["time"])
        buys = [t for t in at if t["side"] == "BUY"]
        sells = [t for t in at if t["side"] == "SELL"]

        if asset not in asset_stats:
            asset_stats[asset] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0, "volume": 0}

        # Pair buys with sells
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
                "entry_time": datetime.fromtimestamp(b["time"] / 1000, tz=timezone.utc).isoformat() if b["time"] else "",
                "exit_time": datetime.fromtimestamp(s["time"] / 1000, tz=timezone.utc).isoformat() if s["time"] else "",
                "buy_commission": b["commission"],
                "sell_commission": s["commission"],
            }
            round_trips.append(rt)
            asset_stats[asset]["trades"] += 1
            asset_stats[asset]["pnl"] = round(asset_stats[asset]["pnl"] + pnl, 2)
            asset_stats[asset]["volume"] = round(asset_stats[asset]["volume"] + b["quote_qty"] + s["quote_qty"], 2)
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

    return {
        "platform": "binance_testnet",
        "connected": True,
        "account": {
            "balances": balances,
        },
        "summary": {
            "total_trades": len(round_trips),
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(round_trips) - len(wins) - len(losses),
            "win_rate": round(wr, 4),
            "total_pnl": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(pf, 2),
            "avg_win": round(gross_profit / max(1, len(wins)), 2),
            "avg_loss": round(gross_loss / max(1, len(losses)), 2),
            "best_trade": max(round_trips, key=lambda x: x["pnl"]) if round_trips else None,
            "worst_trade": min(round_trips, key=lambda x: x["pnl"]) if round_trips else None,
            "total_volume": round(sum(a["volume"] for a in asset_stats.values()), 2),
            "total_commissions": round(sum(t.get("commission", 0) for t in trades), 4),
        },
        "by_asset": dict(sorted(asset_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)),
        "trades": round_trips,
        "raw_fills": trades[:100],
        "raw_orders": orders[:100],
    }


@router.get("/alpaca/live")
async def alpaca_live_data():
    """Pull all data directly from Alpaca Paper Trading API."""
    from bahamut.execution.alpaca_adapter import (
        get_account, get_all_orders, get_all_positions, get_activities,
        get_portfolio_history, _configured
    )

    if not _configured():
        return {"error": "Alpaca not configured. Set ALPACA_API_KEY."}

    # Pull everything from Alpaca
    account = get_account()
    orders = get_all_orders(status="all")
    positions = get_all_positions()
    fills = get_activities("FILL")

    # Pair buy/sell fills to compute PnL per round-trip
    asset_buys: dict[str, list] = {}
    asset_sells: dict[str, list] = {}
    for f in fills:
        a = f["asset"]
        if f["side"] == "buy":
            asset_buys.setdefault(a, []).append(f)
        else:
            asset_sells.setdefault(a, []).append(f)

    round_trips = []
    asset_stats: dict[str, dict] = {}

    all_assets = set(list(asset_buys.keys()) + list(asset_sells.keys()))
    for asset in all_assets:
        buys = sorted(asset_buys.get(asset, []), key=lambda x: x.get("transaction_time", ""))
        sells = sorted(asset_sells.get(asset, []), key=lambda x: x.get("transaction_time", ""))

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
                "entry_time": b.get("transaction_time", ""),
                "exit_time": s.get("transaction_time", ""),
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

    return {
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
            "total_pnl": round(total_pnl, 2),
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
