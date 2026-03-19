"""
Bahamut.AI — Observability Middleware

Provides:
  1. Request ID generation and propagation
  2. Slow request tracking (>500ms)
  3. Structured logging context per request
"""
import time
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

# Threshold for logging slow requests (milliseconds)
SLOW_REQUEST_THRESHOLD_MS = 500


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Adds request_id to every request and logs slow responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
        start = time.monotonic()

        # Extract user context if available (from JWT)
        user_id = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jose import jwt
                from bahamut.config import get_settings
                token = auth_header.split(" ", 1)[1]
                payload = jwt.decode(token, get_settings().jwt_secret,
                                     algorithms=["HS256"], options={"verify_exp": False})
                user_id = payload.get("sub", "")[:12]
            except Exception:
                pass

        # Bind structured log context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        if user_id:
            structlog.contextvars.bind_contextvars(user_id=user_id)

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            logger.error("request_exception",
                         status=500, elapsed_ms=elapsed_ms,
                         error=str(e)[:200])
            raise

        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Log slow requests
        if elapsed_ms > SLOW_REQUEST_THRESHOLD_MS:
            logger.warning("slow_request",
                           status=response.status_code,
                           elapsed_ms=elapsed_ms)

        # Log all non-health requests at debug level
        if not request.url.path.endswith("/health"):
            logger.debug("request_completed",
                         status=response.status_code,
                         elapsed_ms=elapsed_ms)

        return response
