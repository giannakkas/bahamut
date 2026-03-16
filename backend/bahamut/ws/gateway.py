"""
Bahamut.AI WebSocket Gateway
Handles real-time client connections, Redis pub/sub bridging, and event routing.
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt
import structlog

from bahamut.config import get_settings
from bahamut.shared.redis_client import redis_manager

router = APIRouter()
logger = structlog.get_logger()
settings = get_settings()


class ConnectionManager:
    """Manages WebSocket connections per user."""

    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = {}
        self.asset_subs: dict[str, set[str]] = {}  # asset -> user_ids

    async def connect(self, ws: WebSocket, user_id: str):
        await ws.accept()
        if user_id not in self.connections:
            self.connections[user_id] = set()
        self.connections[user_id].add(ws)
        logger.info("ws_connected", user_id=user_id, total=len(self.connections))

    def disconnect(self, ws: WebSocket, user_id: str):
        if user_id in self.connections:
            self.connections[user_id].discard(ws)
            if not self.connections[user_id]:
                del self.connections[user_id]
        # Clean up asset subscriptions
        for asset, users in list(self.asset_subs.items()):
            users.discard(user_id)
            if not users:
                del self.asset_subs[asset]
        logger.info("ws_disconnected", user_id=user_id)

    async def send_to_user(self, user_id: str, event: str, data: dict):
        if user_id in self.connections:
            payload = json.dumps({"event": event, "data": data})
            dead = set()
            for ws in self.connections[user_id]:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                self.connections[user_id].discard(ws)

    async def broadcast(self, event: str, data: dict):
        payload = json.dumps({"event": event, "data": data})
        for user_id, sockets in self.connections.items():
            dead = set()
            for ws in sockets:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                sockets.discard(ws)

    def subscribe_asset(self, user_id: str, asset: str):
        if asset not in self.asset_subs:
            self.asset_subs[asset] = set()
        self.asset_subs[asset].add(user_id)

    def unsubscribe_asset(self, user_id: str, asset: str):
        if asset in self.asset_subs:
            self.asset_subs[asset].discard(user_id)


manager = ConnectionManager()


def authenticate_ws(token: str) -> Optional[dict]:
    """Verify JWT token for WebSocket connection."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


async def redis_subscriber(user_id: str, ws: WebSocket):
    """Subscribe to Redis channels and forward events to WebSocket client."""
    if not redis_manager.redis:
        return

    pubsub = redis_manager.redis.pubsub()
    channels = [
        f"bahamut:signals:{user_id}",
        f"bahamut:trades:{user_id}",
        f"bahamut:risk:{user_id}",
        "bahamut:regime",
        "bahamut:learning",
        "bahamut:system",
        "bahamut:agents",
    ]

    try:
        await pubsub.subscribe(*channels)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await ws.send_text(message["data"])
                except Exception:
                    break
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.close()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(None)):
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    payload = authenticate_ws(token)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    await manager.connect(ws, user_id)

    # Start Redis subscriber in background
    subscriber_task = asyncio.create_task(redis_subscriber(user_id, ws))

    try:
        while True:
            data = await ws.receive_json()
            event = data.get("event", "")

            if event == "subscribe_asset":
                asset = data.get("data", {}).get("asset", "")
                if asset:
                    manager.subscribe_asset(user_id, asset)
                    await ws.send_text(json.dumps({
                        "event": "subscribed", "data": {"asset": asset}
                    }))

            elif event == "unsubscribe_asset":
                asset = data.get("data", {}).get("asset", "")
                if asset:
                    manager.unsubscribe_asset(user_id, asset)

            elif event == "ping":
                await ws.send_text(json.dumps({"event": "pong", "data": {}}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("ws_error", user_id=user_id, error=str(e))
    finally:
        subscriber_task.cancel()
        manager.disconnect(ws, user_id)


# ── Helper for other services to push events ──
async def push_to_user(user_id: str, event: str, data: dict):
    """Push event to user via Redis pub/sub (reaches all API instances)."""
    channel = f"bahamut:trades:{user_id}" if "trade" in event else f"bahamut:signals:{user_id}"
    await redis_manager.publish(channel, {"event": event, "data": data})


async def push_global(event: str, data: dict):
    """Push event to all connected clients."""
    channel = "bahamut:regime" if "regime" in event else "bahamut:system"
    await redis_manager.publish(channel, {"event": event, "data": data})
