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
        order_status = o.get("X", "")  # NEW, FILLED, PARTIALLY_FILLED, etc.
        client_order_id = o.get("c", "")
        fill_price = float(o.get("L", 0))  # last fill price
        fill_qty = float(o.get("l", 0))    # last fill qty
        avg_price = float(o.get("ap", 0))  # avg fill price
        total_qty = float(o.get("z", 0))   # total filled qty

        if exec_type == "TRADE":
            logger.info("binance_fill_event",
                        order_id=order_id, symbol=symbol, side=side,
                        fill_price=fill_price, fill_qty=fill_qty,
                        avg_price=avg_price, total_qty=total_qty,
                        status=order_status, client_order_id=client_order_id)

            _publish_fill_to_redis(
                order_id=order_id, symbol=symbol, side=side,
                fill_price=avg_price if avg_price > 0 else fill_price,
                fill_qty=total_qty if total_qty > 0 else fill_qty,
                order_status=order_status,
                client_order_id=client_order_id,
            )

            # Try to match and update OrderManager
            try:
                from bahamut.execution.order_manager import OrderManager
                mgr = OrderManager()
                # Look up intent by client_order_id or broker_order_id
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
                        fill_price=avg_price if avg_price > 0 else fill_price,
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
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        await _process_event(data)
                    except Exception as e:
                        logger.error("binance_stream_event_error",
                                     error=str(e)[:100])

        except Exception as e:
            logger.error("binance_user_stream_disconnect",
                         error=str(e)[:100])
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
