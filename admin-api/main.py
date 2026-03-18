"""
Bahamut TICC — FastAPI Backend
Trading Intelligence Control Center API

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from routers.auth_router import router as auth_router, limiter
from routers.admin_router import router as admin_router
from routers.portfolio_router import router as portfolio_router
from services.database import init_db

# ─── Settings ─────────────────────────────────────────────────────

settings = get_settings()

# ─── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bahamut")

# ─── Lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Bahamut TICC API")
    settings.validate_for_production()
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down Bahamut TICC API")

# ─── App ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Bahamut TICC API",
    description="Trading Intelligence Control Center — Admin Backend",
    version="1.0.0",
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    lifespan=lifespan,
)

# ─── Rate Limiting ────────────────────────────────────────────────

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ─── Exception Handlers ──────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    # Never leak stack traces to client
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )

# ─── Routers ──────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(portfolio_router)

# ─── Health / Ready ───────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bahamut-ticc"}

@app.get("/ready", tags=["system"])
async def ready():
    """Readiness check — verifies DB is accessible."""
    from sqlalchemy import text as sa_text
    from services.database import get_session
    try:
        with get_session() as session:
            session.execute(sa_text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready"})

# ─── Entrypoint ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
