"""
Bahamut.AI — Broker Reconciliation Loop

Periodically compares local order/position state against broker truth.
Detects and handles:
  - Orphan broker positions (position on broker, no local record)
  - Missing broker positions (local record says open, broker has nothing)
  - Size mismatches (local filled_qty != broker qty)
  - Status mismatches (local says filled, broker says canceled)

Runs:
  - At startup (after Redis rehydration)
  - Every N minutes via Celery beat
  - On demand from admin panel

Usage:
  from bahamut.execution.reconciliation import reconcile_all
  result = reconcile_all()
  # Returns: {matched, mismatches, orphans, missing, actions_taken}
"""
import os
import time
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def reconcile_all() -> dict:
    """Full reconciliation of all brokers.

    Returns:
      {
        "binance": {...},
        "alpaca": {...},
        "summary": {matched, mismatches, orphans, missing, actions},
        "reconciled_at": ISO timestamp,
      }
    """
    results = {}
    try:
        results["binance"] = _reconcile_binance()
    except Exception as e:
        results["binance"] = {"error": str(e)[:200]}
        logger.error("reconciliation_binance_failed", error=str(e)[:200])

    try:
        results["alpaca"] = _reconcile_alpaca()
    except Exception as e:
        results["alpaca"] = {"error": str(e)[:200]}
        logger.error("reconciliation_alpaca_failed", error=str(e)[:200])

    # Aggregate summary
    total_matched = sum(r.get("matched", 0) for r in results.values() if isinstance(r, dict))
    total_mismatches = sum(len(r.get("mismatches", [])) for r in results.values() if isinstance(r, dict))
    total_orphans = sum(len(r.get("orphans", [])) for r in results.values() if isinstance(r, dict))
    total_missing = sum(len(r.get("missing_on_broker", [])) for r in results.values() if isinstance(r, dict))
    total_actions = sum(len(r.get("actions_taken", [])) for r in results.values() if isinstance(r, dict))

    results["summary"] = {
        "matched": total_matched,
        "mismatches": total_mismatches,
        "orphans": total_orphans,
        "missing_on_broker": total_missing,
        "actions_taken": total_actions,
    }
    results["reconciled_at"] = datetime.now(timezone.utc).isoformat()

    # Persist summary to Redis for diagnostics
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        r.setex("bahamut:reconciliation:last",
                86400,
                json.dumps(results, default=str))
    except Exception:
        pass

    if total_mismatches > 0 or total_orphans > 0 or total_missing > 0:
        logger.error("reconciliation_discrepancies_found",
                     mismatches=total_mismatches,
                     orphans=total_orphans,
                     missing=total_missing,
                     actions=total_actions)
    else:
        logger.info("reconciliation_clean",
                    matched=total_matched)

    return results


def _reconcile_binance() -> dict:
    """Reconcile Binance Futures positions against local state."""
    result = {
        "platform": "binance_futures",
        "matched": 0,
        "mismatches": [],
        "orphans": [],
        "missing_on_broker": [],
        "actions_taken": [],
    }

    # Fetch broker positions
    broker_positions = {}
    try:
        from bahamut.execution.binance_futures import get_account, SYMBOL_MAP
        account = get_account()
        if not account:
            result["error"] = "binance account fetch failed"
            return result

        # Build map of broker positions with non-zero qty
        for pos in account.get("positions", []):
            qty = abs(float(pos.get("positionAmt", 0)))
            if qty > 0:
                symbol = pos.get("symbol", "")
                # Reverse-map: BTCUSDT → BTCUSD
                _reverse = {v: k for k, v in SYMBOL_MAP.items()}
                asset = _reverse.get(symbol, symbol.replace("USDT", "USD"))
                broker_positions[asset] = {
                    "symbol": symbol,
                    "qty": qty,
                    "entry_price": float(pos.get("entryPrice", 0)),
                    "unrealized_pnl": float(pos.get("unrealizedProfit", 0)),
                    "side": "LONG" if float(pos.get("positionAmt", 0)) > 0 else "SHORT",
                }
    except Exception as e:
        result["error"] = f"broker fetch failed: {str(e)[:150]}"
        return result

    # Fetch local positions (from order_intents + training_positions)
    local_positions = {}
    try:
        from bahamut.execution.order_manager import OrderManager
        mgr = OrderManager()
        for intent in mgr.get_open_intents():
            asset = intent.get("asset", "")
            if intent.get("execution_platform") == "binance_futures":
                local_positions[asset] = {
                    "intent_id": intent["id"],
                    "direction": intent["direction"],
                    "filled_qty": float(intent.get("filled_qty", 0)),
                    "avg_fill_price": float(intent.get("avg_fill_price", 0)),
                    "order_state": intent.get("order_state"),
                }
    except Exception:
        # Fallback: use training_positions
        try:
            from bahamut.training.engine import _load_positions
            for pos in _load_positions():
                if pos.execution_platform == "binance_futures":
                    local_positions[pos.asset] = {
                        "intent_id": pos.position_id,
                        "direction": pos.direction,
                        "filled_qty": pos.size,
                        "avg_fill_price": pos.entry_price,
                        "order_state": "filled",
                    }
        except Exception:
            pass

    # Compare
    all_assets = set(list(broker_positions.keys()) + list(local_positions.keys()))
    for asset in all_assets:
        on_broker = broker_positions.get(asset)
        on_local = local_positions.get(asset)

        if on_broker and on_local:
            # Both exist — check for mismatches
            qty_match = abs(on_broker["qty"] - on_local["filled_qty"]) < on_broker["qty"] * 0.01
            dir_match = on_broker["side"] == on_local["direction"]

            if qty_match and dir_match:
                result["matched"] += 1
            else:
                mismatch = {
                    "asset": asset,
                    "broker_qty": on_broker["qty"],
                    "local_qty": on_local["filled_qty"],
                    "broker_side": on_broker["side"],
                    "local_direction": on_local["direction"],
                    "qty_match": qty_match,
                    "dir_match": dir_match,
                }
                result["mismatches"].append(mismatch)
                logger.error("reconciliation_mismatch",
                             asset=asset, **mismatch)

                # Action: mark for reconciliation
                try:
                    from bahamut.execution.order_manager import OrderManager, OrderState
                    mgr = OrderManager()
                    mgr.transition(on_local["intent_id"],
                                   OrderState.RECONCILE_REQUIRED,
                                   {"mismatch": mismatch})
                    result["actions_taken"].append({
                        "asset": asset,
                        "action": "marked_reconcile_required",
                    })
                except Exception:
                    pass

        elif on_broker and not on_local:
            # ORPHAN: position on broker but no local record
            result["orphans"].append({
                "asset": asset,
                "broker_qty": on_broker["qty"],
                "broker_side": on_broker["side"],
                "entry_price": on_broker["entry_price"],
            })
            logger.error("reconciliation_orphan_position",
                         asset=asset, qty=on_broker["qty"],
                         side=on_broker["side"])

        elif on_local and not on_broker:
            # MISSING: local says open but broker has no position
            # This could mean the broker closed it (SL/TP hit on broker side)
            # or the open never actually filled.
            result["missing_on_broker"].append({
                "asset": asset,
                "local_qty": on_local["filled_qty"],
                "local_direction": on_local["direction"],
                "order_state": on_local["order_state"],
            })
            logger.error("reconciliation_missing_on_broker",
                         asset=asset,
                         local_qty=on_local["filled_qty"],
                         state=on_local["order_state"])

    return result


def _reconcile_alpaca() -> dict:
    """Reconcile Alpaca positions against local state."""
    result = {
        "platform": "alpaca",
        "matched": 0,
        "mismatches": [],
        "orphans": [],
        "missing_on_broker": [],
        "actions_taken": [],
    }

    # Fetch broker positions
    try:
        from bahamut.execution.alpaca_adapter import get_positions
        positions = get_positions()
        if positions is None:
            result["error"] = "alpaca not configured or fetch failed"
            return result

        broker_positions = {}
        for pos in positions:
            symbol = pos.get("symbol", "")
            qty = abs(float(pos.get("qty", 0)))
            if qty > 0:
                broker_positions[symbol] = {
                    "qty": qty,
                    "side": pos.get("side", "long").upper(),
                    "entry_price": float(pos.get("avg_entry_price", 0)),
                    "unrealized_pnl": float(pos.get("unrealized_pl", 0)),
                }

        # Fetch local stock positions
        local_positions = {}
        try:
            from bahamut.training.engine import _load_positions
            for pos in _load_positions():
                if pos.asset_class == "stock" and pos.execution_platform in ("alpaca", "alpaca_paper"):
                    local_positions[pos.asset] = {
                        "position_id": pos.position_id,
                        "direction": pos.direction,
                        "size": pos.size,
                        "entry_price": pos.entry_price,
                    }
        except Exception:
            pass

        # Compare
        all_symbols = set(list(broker_positions.keys()) + list(local_positions.keys()))
        for sym in all_symbols:
            on_broker = broker_positions.get(sym)
            on_local = local_positions.get(sym)

            if on_broker and on_local:
                qty_ok = abs(on_broker["qty"] - on_local["size"]) < on_broker["qty"] * 0.02
                if qty_ok:
                    result["matched"] += 1
                else:
                    result["mismatches"].append({
                        "asset": sym, "broker_qty": on_broker["qty"],
                        "local_qty": on_local["size"],
                    })
            elif on_broker and not on_local:
                result["orphans"].append({
                    "asset": sym, "broker_qty": on_broker["qty"],
                    "broker_side": on_broker["side"],
                })
            elif on_local and not on_broker:
                result["missing_on_broker"].append({
                    "asset": sym, "local_qty": on_local["size"],
                    "direction": on_local["direction"],
                })

    except ImportError:
        result["error"] = "alpaca adapter not available"
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def get_last_reconciliation() -> dict | None:
    """Read the last reconciliation result from Redis."""
    try:
        import redis, json
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=2)
        raw = r.get("bahamut:reconciliation:last")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None
