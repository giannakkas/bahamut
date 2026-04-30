"""
Orphan Position Diagnostic — Query Binance Futures for orphan details.

Reports for each orphan:
  - Current PnL, entry price, mark price
  - Whether SL/TP orders exist on exchange
  - Position size in USD
  - Recommendation (adopt/close/dust)

Run: railway run python backend/scripts/orphan_diagnostic.py

Also: resets Binance circuit breaker (accumulated failures from old STOP_MARKET bug).
"""
import os
import sys
import time
import json
import hmac
import hashlib
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE_URL = os.environ.get("BINANCE_FUTURES_BASE_URL", "https://demo-fapi.binance.com")
API_KEY = os.environ.get("BINANCE_FUTURES_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_FUTURES_API_SECRET", "")

SYMBOL_MAP = {
    "AVAXUSD": "AVAXUSDT", "APTUSD": "APTUSDT", "ATOMUSD": "ATOMUSDT",
    "LINKUSD": "LINKUSDT", "NEARUSD": "NEARUSDT", "BNBUSD": "BNBUSDT",
    "DOGEUSD": "DOGEUSDT", "SOLUSD": "SOLUSDT", "JUPUSD": "JUPUSDT",
    "XRPUSD": "XRPUSDT", "LTCUSD": "LTCUSDT", "FILUSD": "FILUSDT",
    "TIAUSD": "TIAUSDT", "INJUSD": "INJUSDT", "FETUSD": "FETUSDT",
    "ARBUSD": "ARBUSDT",
}
REVERSE_MAP = {v: k for k, v in SYMBOL_MAP.items()}


def _sign(params: dict) -> dict:
    params["timestamp"] = str(int(time.time() * 1000))
    params["recvWindow"] = "5000"
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def _headers():
    return {"X-MBX-APIKEY": API_KEY}


def get_positions():
    """Get all open positions from Binance."""
    params = _sign({})
    r = httpx.get(f"{BASE_URL}/fapi/v2/positionRisk", params=params,
                  headers=_headers(), timeout=10)
    if r.status_code != 200:
        print(f"ERROR: positionRisk returned {r.status_code}: {r.text[:200]}")
        return []
    positions = []
    for p in r.json():
        qty = abs(float(p.get("positionAmt", 0)))
        if qty > 0:
            positions.append({
                "symbol": p["symbol"],
                "asset": REVERSE_MAP.get(p["symbol"], p["symbol"]),
                "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "qty": qty,
                "entry_price": float(p.get("entryPrice", 0)),
                "mark_price": float(p.get("markPrice", 0)),
                "pnl": float(p.get("unRealizedProfit", 0)),
                "notional": abs(float(p.get("notional", 0))),
                "leverage": int(p.get("leverage", 1)),
            })
    return positions


def get_open_orders(symbol=None):
    """Get all open orders, optionally filtered by symbol."""
    params = {}
    if symbol:
        params["symbol"] = symbol
    params = _sign(params)
    r = httpx.get(f"{BASE_URL}/fapi/v1/openOrders", params=params,
                  headers=_headers(), timeout=10)
    if r.status_code != 200:
        print(f"ERROR: openOrders returned {r.status_code}: {r.text[:200]}")
        return []
    return r.json()


def get_tracked_positions():
    """Get positions tracked by our system from Redis/DB."""
    tracked = set()
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        positions = r.hgetall("bahamut:training:positions")
        for pid, data in positions.items():
            try:
                pos = json.loads(data)
                tracked.add(pos.get("asset", ""))
            except Exception:
                pass
    except Exception as e:
        print(f"WARNING: Could not read Redis positions: {e}")
    return tracked


def run():
    if not API_KEY or not API_SECRET:
        print("ERROR: BINANCE_FUTURES_API_KEY and BINANCE_FUTURES_API_SECRET required.")
        print("Run with: railway run python backend/scripts/orphan_diagnostic.py")
        sys.exit(1)

    print(f"\n{'=' * 90}")
    print(f"ORPHAN POSITION DIAGNOSTIC — {BASE_URL}")
    print(f"{'=' * 90}")

    # 1. Get all exchange positions
    positions = get_positions()
    print(f"\nExchange positions: {len(positions)}")

    # 2. Get tracked positions
    tracked = get_tracked_positions()
    print(f"Tracked by system: {len(tracked)} assets")

    # 3. Get ALL open orders
    all_orders = get_open_orders()
    orders_by_symbol = {}
    for o in all_orders:
        sym = o["symbol"]
        if sym not in orders_by_symbol:
            orders_by_symbol[sym] = []
        orders_by_symbol[sym].append({
            "orderId": o["orderId"],
            "type": o["type"],
            "side": o["side"],
            "stopPrice": float(o.get("stopPrice", 0)),
            "price": float(o.get("price", 0)),
            "origQty": float(o.get("origQty", 0)),
            "status": o["status"],
        })
    print(f"Open orders on exchange: {len(all_orders)}")

    # 4. Classify each position
    orphans = []
    tracked_positions = []
    for p in positions:
        asset = p["asset"]
        symbol = p["symbol"]
        is_tracked = asset in tracked
        sym_orders = orders_by_symbol.get(symbol, [])

        # Find SL/TP orders
        sl_orders = [o for o in sym_orders if o["type"] in ("STOP", "STOP_MARKET") and o["stopPrice"] > 0]
        tp_orders = [o for o in sym_orders if o["type"] in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET") and o["stopPrice"] > 0]

        p["has_sl"] = len(sl_orders) > 0
        p["has_tp"] = len(tp_orders) > 0
        p["sl_price"] = sl_orders[0]["stopPrice"] if sl_orders else None
        p["tp_price"] = tp_orders[0]["stopPrice"] if tp_orders else None
        p["is_tracked"] = is_tracked
        p["orders"] = sym_orders

        if is_tracked:
            tracked_positions.append(p)
        else:
            orphans.append(p)

    # 5. Report
    print(f"\n{'=' * 90}")
    print(f"ORPHAN POSITIONS ({len(orphans)})")
    print(f"{'=' * 90}")
    print(f"{'Asset':<12} {'Side':<6} {'Qty':>10} {'Entry':>10} {'Mark':>10} {'PnL':>10} {'Notional':>10} {'SL':>5} {'TP':>5} {'Recommendation'}")
    print("-" * 100)

    total_orphan_pnl = 0
    for p in sorted(orphans, key=lambda x: abs(x["pnl"]), reverse=True):
        total_orphan_pnl += p["pnl"]
        # Recommendation logic
        is_dust = p["notional"] < 5
        is_profitable = p["pnl"] > 0
        has_brackets = p["has_sl"] and p["has_tp"]

        if is_dust:
            rec = "CLOSE (dust)"
        elif has_brackets and is_profitable:
            rec = "ADOPT or HOLD"
        elif has_brackets and not is_profitable:
            rec = "MONITOR (has brackets)"
        elif not has_brackets and is_profitable:
            rec = "CLOSE (no protection)"
        else:
            rec = "CLOSE (no protection, losing)"

        print(f"{p['asset']:<12} {p['side']:<6} {p['qty']:>10} {p['entry_price']:>10.4f} "
              f"{p['mark_price']:>10.4f} {p['pnl']:>10.2f} {p['notional']:>10.2f} "
              f"{'Y' if p['has_sl'] else 'N':>5} {'Y' if p['has_tp'] else 'N':>5} {rec}")

    print(f"\n  Total orphan unrealized PnL: ${total_orphan_pnl:.2f}")

    # 6. Bracket coverage for tracked positions
    print(f"\n{'=' * 90}")
    print(f"TRACKED POSITIONS — BRACKET STATUS ({len(tracked_positions)})")
    print(f"{'=' * 90}")
    for p in tracked_positions:
        status = "OK" if p["has_sl"] and p["has_tp"] else "MISSING BRACKETS"
        print(f"  {p['asset']:<12} {p['side']:<6} SL={'Y' if p['has_sl'] else 'N'} "
              f"TP={'Y' if p['has_tp'] else 'N'}  {status}")
        if not p["has_sl"] or not p["has_tp"]:
            print(f"    → Orders on exchange: {p['orders']}")

    # 7. Reset circuit breaker
    print(f"\n{'=' * 90}")
    print(f"CIRCUIT BREAKER RESET")
    print(f"{'=' * 90}")
    try:
        from bahamut.execution.circuit_breaker import circuit_breaker_binance
        status_before = circuit_breaker_binance.get_status()
        print(f"  Before: state={status_before['state']} failures={status_before['failure_count']}")
        circuit_breaker_binance.force_reset()
        status_after = circuit_breaker_binance.get_status()
        print(f"  After:  state={status_after['state']} failures={status_after['failure_count']}")
        print(f"  ✓ Circuit breaker reset to CLOSED")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n{'=' * 90}")
    print(f"ACTION REQUIRED:")
    print(f"  1. Review orphan recommendations above")
    print(f"  2. Close orphans via Binance demo UI (Positions tab → Close)")
    print(f"  3. For tracked positions missing brackets: they'll auto-repair next cycle")
    print(f"     (reconciliation.py bracket_repair uses STOP/TAKE_PROFIT limit orders)")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    run()
