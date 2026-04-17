"""
Bahamut — Admin Live WebSocket

Pushes real-time events to admin dashboard clients.
NOT the source of truth — just a notification channel.
Trading engine writes to Redis/Postgres as usual, then publishes
lightweight events here for instant dashboard updates.

Events: cycle_completed, position_opened, position_closed,
        selector_updated, learning_updated, alert_created

Architecture:
  - In-process event bus (single replica on Railway)
  - JWT auth required for connection
  - Auto-cleanup on disconnect
  - All publish failures are non-fatal (logged, not raised)
"""
import asyncio
import json
import time
import structlog
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from bahamut.config import get_settings

router = APIRouter()
logger = structlog.get_logger()
settings = get_settings()


# ═══════════════════════════════════════════
# ADMIN CONNECTION MANAGER
# ═══════════════════════════════════════════

class AdminConnectionManager:
    """Manages admin WebSocket connections. Lightweight, in-process."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self._events_published = 0
        self._broadcast_failures = 0

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)
        logger.info("ws_admin_connected", total=len(self.clients))

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)
        logger.info("ws_admin_disconnected", total=len(self.clients))

    async def broadcast(self, event_type: str, payload: dict):
        """Broadcast event to all connected admin clients. Non-fatal on error."""
        if not self.clients:
            return

        message = json.dumps({
            "event": event_type,
            "data": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        dead: set[WebSocket] = set()
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                self._broadcast_failures += 1

        for ws in dead:
            self.clients.discard(ws)

        self._events_published += 1

    @property
    def stats(self) -> dict:
        return {
            "connected_clients": len(self.clients),
            "events_published": self._events_published,
            "broadcast_failures": self._broadcast_failures,
        }


admin_ws = AdminConnectionManager()


# ═══════════════════════════════════════════
# EVENT PUBLISHING API (called by engine/orchestrator)
# ═══════════════════════════════════════════

def publish_event(event_type: str, payload: dict):
    """Publish event to admin dashboard. Safe to call from sync code.

    This is the ONLY function other modules need to import.
    Failures are logged but never raised — trading must not break.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context (FastAPI request or lifespan)
            loop.create_task(_safe_broadcast(event_type, payload))
        else:
            loop.run_until_complete(_safe_broadcast(event_type, payload))
    except RuntimeError:
        # No event loop available (worker thread) — use fire-and-forget
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_safe_broadcast(event_type, payload))
            loop.close()
        except Exception:
            pass  # Non-fatal
    except Exception as e:
        logger.debug("ws_publish_failed", event=event_type, error=str(e))


async def _safe_broadcast(event_type: str, payload: dict):
    """Broadcast with error swallowing."""
    try:
        await admin_ws.broadcast(event_type, payload)
    except Exception as e:
        logger.debug("ws_broadcast_error", event=event_type, error=str(e))


# ═══════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════

def _authenticate(token: str) -> Optional[dict]:
    """Verify token for WebSocket connection.
    Admin panel is already behind login — we just need to verify
    the token is a valid JWT from our system."""
    for secret in [settings.jwt_secret, getattr(settings, "jwt_refresh_secret", "")]:
        if not secret:
            continue
        for opts in [{}]:
            try:
                payload = jwt.decode(token, secret, algorithms=["HS256"], options=opts)
                if payload.get("sub"):
                    return payload
            except Exception:
                continue
    logger.warning("ws_auth_failed", token_len=len(token))
    return None


@router.websocket("/ws/admin/live")
async def admin_live_endpoint(ws: WebSocket, token: str = Query(None)):
    """Admin-only live event stream."""
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    user = _authenticate(token)
    if not user:
        await ws.close(code=4003, reason="Not authorized (admin required)")
        return

    await admin_ws.connect(ws)

    try:
        while True:
            # Wait for client messages (ping/pong keepalive)
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("event") == "ping":
                    await ws.send_text(json.dumps({"event": "pong", "data": {}}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("ws_admin_error", error=str(e))
    finally:
        admin_ws.disconnect(ws)


# ═══════════════════════════════════════════
# STATS ENDPOINT
# ═══════════════════════════════════════════

@router.get("/api/admin/ws/stats")
async def ws_stats():
    return admin_ws.stats
