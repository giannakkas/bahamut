"""
Binance Futures user-data stream — event-driven fill + order updates.

Binance pushes ACCOUNT_UPDATE and ORDER_TRADE_UPDATE events via a
persistent WebSocket connection. This eliminates polling for fills.

Runs as a dedicated process (separate from Celery workers).
Entry: python -c "from bahamut.execution.binance_user_stream import run_forever; run_forever()"

Events handled:
  ORDER_TRADE_UPDATE (x=TRADE) → fill confirmation → OrderManager + Redis
  ACCOUNT_UPDATE → position/balance changes (logged for audit)
"""
import asyncio
import json
import os
import time
import structlog

logger = structlog.get_logger()

_WS_BASE = os.environ.get("BINANCE_FUTURES_WS_URL",
                           "wss://stream.binancefuture.com/ws")
_RECONNECT_DELAY = 5
_KEEPALIVE_INTERVAL = 1800  # 30 minutes


def _api_base():
    return os.environ.get("BINANCE_FUTURES_BASE_URL",
                          "https://testnet.binancefuture.com")


def _headers():
    return {
        "X-MBX-APIKEY": os.environ.get("BINANCE_FUTURES_API_KEY", ""),
    }


async def _get_listen_key() -> str | None:
    """Create a listenKey for the user-data stream."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{_api_base()}/fapi/v1/listenKey",
                headers=_headers(),
            )
            if r.status_code == 200:
                key = r.json().get("listenKey")
                logger.info("binance_listen_key_obtained", key=key[:8] + "...")
                return key
            logger.error("binance_listen_key_failed", status=r.status_code)
    except Exception as e:
        logger.error("binance_listen_key_error", error=str(e)[:100])
    return None


async def _keepalive_loop(key: str):
    """Refresh listenKey every 30 minutes to prevent expiry."""
    while True:
        await asyncio.sleep(_KEEPALIVE_INTERVAL)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.put(
                    f"{_api_base()}/fapi/v1/listenKey",
                    headers=_headers(),
                    params={"listenKey": key},
                )
                if r.status_code == 200:
                    logger.debug("binance_listen_key_refreshed")
                else:
                    logger.warning("binance_listen_key_refresh_failed",
                                   status=r.status_code)
        except Exception as e:
            logger.error("binance_listen_key_keepalive_error", error=str(e)[:100])


def _publish_fill_to_redis(order_id: str, symbol: str, side: str,
                           fill_price: float, fill_qty: float,
                           order_status: str, client_order_id: str):
    """Write fill event to Redis for cross-process visibility."""
    try:
        import redis
        r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        entry = json.dumps({
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "fill_price": fill_price,
            "fill_qty": fill_qty,
            "status": order_status,
            "client_order_id": client_order_id,
            "ts": time.time(),
        })
        r.setex(f"bahamut:fills:{order_id}", 3600, entry)
        r.lpush("bahamut:fills:recent", entry)
        r.ltrim("bahamut:fills:recent", 0, 99)
        r.expire("bahamut:fills:recent", 3600)
    except Exception as e:
        logger.warning("fill_redis_publish_failed", error=str(e)[:100])


async def _process_event(data: dict):
    """Handle a single stream event."""
    event_type = data.get("e", "")

    if event_type == "ORDER_TRADE_UPDATE":
        o = data.get("o", {})
        exec_type = o.get("x", "")  # NEW, TRADE, CANCELED, EXPIRED, etc.
        order_id = str(o.get("i", ""))
        symbol = o.get("s", "")
        side = o.get("S", "")
        order_type = o.get("o", "")  # MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
        order_status = o.get("X", "")  # NEW, FILLED, PARTIALLY_FILLED, etc.
        client_order_id = o.get("c", "")
        fill_price = float(o.get("L", 0))  # last fill price
        fill_qty = float(o.get("l", 0))    # last fill qty
        avg_price = float(o.get("ap", 0))  # avg fill price
        total_qty = float(o.get("z", 0))   # total filled qty
        actual_price = avg_price if avg_price > 0 else fill_price

        if exec_type == "TRADE":
            logger.info("binance_fill_event",
                        order_id=order_id, symbol=symbol, side=side,
                        order_type=order_type,
                        fill_price=fill_price, fill_qty=fill_qty,
                        avg_price=avg_price, total_qty=total_qty,
                        status=order_status, client_order_id=client_order_id)

            _publish_fill_to_redis(
                order_id=order_id, symbol=symbol, side=side,
                fill_price=actual_price,
                fill_qty=total_qty if total_qty > 0 else fill_qty,
                order_status=order_status,
                client_order_id=client_order_id,
            )

            # ── BRACKET FILL DETECTION ──
            # If a STOP/TAKE_PROFIT (or legacy STOP_MARKET/TAKE_PROFIT_MARKET) fills,
            # this is an exchange-side SL/TP exit.
            is_bracket = order_type in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT")
            is_bracket_coid = client_order_id.endswith("_sl") or client_order_id.endswith("_tp")

            if is_bracket and order_status == "FILLED" and (is_bracket_coid or is_bracket):
                exit_reason = "SL" if order_type in ("STOP_MARKET", "STOP") else "TP"
                logger.info("stream_bracket_fill_detected",
                            order_id=order_id, symbol=symbol, side=side,
                            order_type=order_type, exit_reason=exit_reason,
                            fill_price=actual_price, client_order_id=client_order_id)
                try:
                    _close_position_from_stream(
                        order_id=order_id,
                        symbol=symbol,
                        client_order_id=client_order_id,
                        fill_price=actual_price,
                        fill_qty=total_qty if total_qty > 0 else fill_qty,
                        exit_reason=exit_reason,
                    )
                except Exception as e:
                    logger.error("stream_bracket_close_failed",
                                 order_id=order_id, symbol=symbol,
                                 error=str(e)[:200])
            else:
                # Non-bracket fill — try to match OrderManager
                try:
                    from bahamut.execution.order_manager import OrderManager
                    mgr = OrderManager()
                    from bahamut.database import sync_engine
                    from sqlalchemy import text
                    with sync_engine.connect() as conn:
                        row = conn.execute(text(
                            "SELECT id FROM order_intents "
                            "WHERE (broker_order_id = :oid OR client_order_id = :coid) "
                            "AND order_state NOT IN ('filled', 'closed') "
                            "ORDER BY created_at DESC LIMIT 1"
                        ), {"oid": order_id, "coid": client_order_id}).fetchone()
                    if row:
                        mgr.record_fill(
                            intent_id=row[0],
                            fill_price=actual_price,
                            fill_qty=total_qty if total_qty > 0 else fill_qty,
                            broker_order_id=order_id,
                            platform="binance_futures",
                        )
                        logger.info("binance_stream_fill_recorded",
                                    intent_id=row[0], order_id=order_id)
                except Exception as e:
                    logger.warning("binance_stream_fill_record_failed",
                                   order_id=order_id, error=str(e)[:100])

        elif exec_type in ("CANCELED", "EXPIRED", "REJECTED"):
            logger.info("binance_order_terminal",
                        order_id=order_id, symbol=symbol,
                        exec_type=exec_type, status=order_status,
                        client_order_id=client_order_id)

    elif event_type == "ACCOUNT_UPDATE":
        reason = data.get("a", {}).get("m", "unknown")
        positions = data.get("a", {}).get("P", [])
        balances = data.get("a", {}).get("B", [])
        logger.debug("binance_account_update",
                     reason=reason,
                     positions_changed=len(positions),
                     balances_changed=len(balances))


def _close_position_from_stream(order_id: str, symbol: str,
                                client_order_id: str, fill_price: float,
                                fill_qty: float, exit_reason: str):
    """Close an internal position when a bracket SL/TP fills on the exchange.

    This is the exchange-side close path. It:
    1. Finds the position by bracket_sl_order_id or bracket_tp_order_id
    2. Sets a Redis flag to prevent client-side double-close
    3. Closes the position with the ACTUAL exchange fill price
    4. Records the trade with closed_via_stream=true
    """
    import redis as _redis
    from bahamut.execution.binance_futures import SYMBOL_MAP

    # Reverse lookup: ATOMUSDT → ATOMUSD
    _reverse = {v: k for k, v in SYMBOL_MAP.items()}
    asset = _reverse.get(symbol, symbol.replace("USDT", "USD"))

    r = _redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        socket_connect_timeout=2,
    )

    # Load positions from Redis and find matching bracket
    from bahamut.trading.engine import _load_positions, _remove_position

    positions = _load_positions()
    matched = None
    for pos in positions:
        if pos.asset != asset:
            continue
        if (pos.bracket_sl_order_id == order_id or
            pos.bracket_tp_order_id == order_id):
            matched = pos
            break
        # Also match by client_order_id prefix
        if client_order_id:
            base_coid = client_order_id.rsplit("_", 1)[0]
            if (pos.exchange_order_id == base_coid or
                pos.client_order_id == base_coid):
                matched = pos
                break

    if not matched:
        logger.warning("stream_bracket_no_position_match",
                       order_id=order_id, asset=asset,
                       client_order_id=client_order_id)
        return

    # Set Redis flag BEFORE closing — client-side checks this
    flag_key = f"bahamut:stream_closed:{matched.position_id}"
    r.setex(flag_key, 600, json.dumps({
        "exit_reason": exit_reason,
        "fill_price": fill_price,
        "order_id": order_id,
        "ts": time.time(),
    }))

    # Cancel the OTHER bracket order (if SL filled, cancel TP and vice versa)
    try:
        from bahamut.execution.binance_futures import cancel_order
        if exit_reason == "SL" and matched.bracket_tp_order_id:
            cancel_order(symbol, matched.bracket_tp_order_id)
            logger.info("stream_cancelled_remaining_bracket",
                        asset=asset, cancelled="TP",
                        order_id=matched.bracket_tp_order_id)
        elif exit_reason == "TP" and matched.bracket_sl_order_id:
            cancel_order(symbol, matched.bracket_sl_order_id)
            logger.info("stream_cancelled_remaining_bracket",
                        asset=asset, cancelled="SL",
                        order_id=matched.bracket_sl_order_id)
    except Exception as e:
        logger.warning("stream_cancel_other_bracket_failed",
                       asset=asset, error=str(e)[:100])

    # Compute PnL from actual fill price
    canonical_entry = (matched.avg_fill_price
                       if matched.avg_fill_price > 0
                       else matched.entry_price)
    if matched.direction == "LONG":
        pnl = (fill_price - canonical_entry) * matched.size
    else:
        pnl = (canonical_entry - fill_price) * matched.size
    pnl_pct = pnl / (matched.risk_amount if matched.risk_amount > 0 else 1)

    # Persist trade to DB
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        from datetime import datetime, timezone
        import uuid

        trade_id = str(uuid.uuid4())[:12]
        exit_time = datetime.now(timezone.utc).isoformat()

        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO training_trades
                (trade_id, position_id, asset, asset_class, strategy, direction,
                 entry_price, exit_price, stop_price, tp_price, size, risk_amount,
                 pnl, pnl_pct, entry_time, exit_time, exit_reason, bars_held, regime,
                 execution_type, confidence_score, trigger_reason, substrategy, data_mode)
                VALUES (:tid, :pid, :a, :ac, :s, :d, :ep, :xp, :sp, :tp, :sz, :ra,
                        :pnl, :pp, :et, :xt, :xr, :bh, :reg,
                        :exec_type, :conf, :trig, :sub, :dm)
            """), {
                "tid": trade_id, "pid": matched.position_id,
                "a": matched.asset, "ac": matched.asset_class,
                "s": matched.strategy, "d": matched.direction,
                "ep": canonical_entry, "xp": fill_price,
                "sp": matched.stop_price, "tp": matched.tp_price,
                "sz": matched.size, "ra": matched.risk_amount,
                "pnl": round(pnl, 4), "pp": round(pnl_pct, 4),
                "et": matched.entry_time, "xt": exit_time,
                "xr": exit_reason, "bh": matched.bars_held,
                "reg": matched.regime,
                "exec_type": matched.execution_type,
                "conf": matched.confidence_score,
                "trig": "stream_bracket_fill",
                "sub": getattr(matched, "substrategy", "") or "",
                "dm": getattr(matched, "data_mode", "live") or "live",
            })
            conn.commit()

        logger.info("stream_trade_persisted",
                    trade_id=trade_id, asset=asset,
                    entry=canonical_entry, exit=fill_price,
                    pnl=round(pnl, 2), exit_reason=exit_reason)
    except Exception as e:
        logger.error("stream_trade_persist_failed",
                     asset=asset, error=str(e)[:200])

    # Remove position from Redis/DB
    _remove_position(matched.position_id)
    logger.info("stream_position_closed",
                asset=asset, position_id=matched.position_id,
                exit_reason=exit_reason, fill_price=fill_price,
                pnl=round(pnl, 2), closed_via_stream=True)

    # Telegram alert
    try:
        from bahamut.monitoring.telegram import send_alert
        emoji = "🟢" if pnl >= 0 else "🔴"
        send_alert(
            f"{emoji} STREAM CLOSE: {asset} {matched.direction} "
            f"exit={exit_reason} fill=${fill_price:.4f} "
            f"PnL=${pnl:.2f} (exchange-side bracket fill)"
        )
    except Exception:
        pass

    # Increment stream close counter
    try:
        r.incr("bahamut:counters:stream_bracket_closes")
        r.expire("bahamut:counters:stream_bracket_closes", 604800)
    except Exception:
        pass


# ═══════════════════════════════════════════
# CONNECTION UPTIME TRACKING
# ═══════════════════════════════════════════

_stream_connected_since: float = 0.0


def _update_uptime(connected: bool):
    """Update stream connection uptime in Redis."""
    global _stream_connected_since
    try:
        import redis as _redis
        r = _redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        if connected:
            if _stream_connected_since == 0:
                _stream_connected_since = time.time()
            uptime = int(time.time() - _stream_connected_since)
            r.setex("bahamut:stream:uptime_seconds", 120, str(uptime))
            r.set("bahamut:stream:status", "connected")
            r.expire("bahamut:stream:status", 120)
        else:
            _stream_connected_since = 0
            r.setex("bahamut:stream:uptime_seconds", 120, "0")
            r.setex("bahamut:stream:status", 120, "disconnected")
    except Exception:
        pass


async def run_stream():
    """Main stream loop. Reconnects on disconnect."""
    api_key = os.environ.get("BINANCE_FUTURES_API_KEY", "")
    if not api_key:
        logger.error("binance_user_stream_no_api_key")
        return

    while True:
        try:
            key = await _get_listen_key()
            if not key:
                logger.warning("binance_user_stream_no_listen_key_retrying")
                await asyncio.sleep(_RECONNECT_DELAY)
                continue

            keepalive_task = asyncio.create_task(_keepalive_loop(key))
            ws_url = f"{_WS_BASE}/{key}"

            try:
                import websockets
            except ImportError:
                logger.error("websockets_not_installed — pip install websockets")
                return

            async with websockets.connect(ws_url, ping_interval=20) as ws:
                logger.info("binance_user_stream_connected", url=ws_url[:50])
                _update_uptime(True)
                async for msg in ws:
                    _update_uptime(True)
                    try:
                        data = json.loads(msg)
                        await _process_event(data)
                    except Exception as e:
                        logger.error("binance_stream_event_error",
                                     error=str(e)[:100])

        except Exception as e:
            logger.error("binance_user_stream_disconnect",
                         error=str(e)[:100])
            _update_uptime(False)
        finally:
            try:
                keepalive_task.cancel()
            except Exception:
                pass

        logger.info("binance_user_stream_reconnecting",
                    delay=_RECONNECT_DELAY)
        await asyncio.sleep(_RECONNECT_DELAY)


def run_forever():
    """Entry point for Railway service."""
    logger.info("binance_user_stream_starting")
    asyncio.run(run_stream())
