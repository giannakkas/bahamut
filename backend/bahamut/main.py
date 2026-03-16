from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog
import traceback

from bahamut.config import get_settings
from bahamut.auth.router import router as auth_router
from bahamut.agents.router import router as agents_router
from bahamut.consensus.router import router as consensus_router
from bahamut.execution.router import router as execution_router
from bahamut.risk.router import router as risk_router
from bahamut.learning.router import router as learning_router
from bahamut.reports.router import router as reports_router
from bahamut.ws.gateway import router as ws_router
from bahamut.shared.redis_client import redis_manager

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Bahamut.AI", environment=settings.environment)
    await redis_manager.connect()
    yield
    await redis_manager.disconnect()
    logger.info("Bahamut.AI shutdown complete")


app = FastAPI(
    title="Bahamut.AI",
    description="Institutional-Grade AI Trading Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)


# Custom middleware to always add CORS headers, even on 500 errors
class CORSAlwaysMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return JSONResponse(
                content={},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                },
            )
        try:
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response
        except Exception as e:
            logger.error("unhandled_error", error=str(e), traceback=traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"detail": str(e)},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                },
            )


app.add_middleware(CORSAlwaysMiddleware)

# Routes
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(agents_router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(consensus_router, prefix="/api/v1/consensus", tags=["consensus"])
app.include_router(execution_router, prefix="/api/v1/execution", tags=["execution"])
app.include_router(risk_router, prefix="/api/v1/risk", tags=["risk"])
app.include_router(learning_router, prefix="/api/v1/learning", tags=["learning"])
app.include_router(reports_router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(ws_router, tags=["websocket"])


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "bahamut-api",
        "version": "1.0.0",
        "environment": settings.environment,
    }
