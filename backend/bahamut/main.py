from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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
from bahamut.billing.router import router as billing_router
from bahamut.ingestion.router import router as market_router
from bahamut.ws.gateway import router as ws_router
from bahamut.paper_trading.router import router as paper_trading_router
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
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "docExpansion": "list",
    },
)

# Mount static files (logo etc.)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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
app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(market_router, prefix="/api/v1/market", tags=["market"])
app.include_router(ws_router, tags=["websocket"])
app.include_router(paper_trading_router, prefix="/api/v1", tags=["paper-trading"])


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "bahamut-api",
        "version": "1.0.0",
        "environment": settings.environment,
    }


@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Bahamut.AI API</title>
<style>
body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0a0b0f;color:#d4af37;font-family:system-ui,sans-serif}
img{max-width:480px;width:90%}
h2{font-weight:400;color:#888;font-size:16px;margin-top:12px}
a{color:#d4af37;text-decoration:none;border:1px solid #d4af3744;padding:10px 28px;border-radius:8px;margin-top:24px;transition:all .2s}
a:hover{background:#d4af3722;border-color:#d4af37}
</style></head><body>
<img src="/static/logo.png" alt="Bahamut.AI"/>
<h2>Institutional-Grade AI Trading Intelligence</h2>
<a href="/docs">API Documentation</a>
</body></html>""")



@app.get("/debug/data-source")
async def debug_data_source():
    """Public debug endpoint to check data source configuration."""
    import os
    from bahamut.config import get_settings
    s = get_settings()
    return {
        "twelve_data_key_set": bool(s.twelve_data_key),
        "twelve_data_key_length": len(s.twelve_data_key) if s.twelve_data_key else 0,
        "twelve_data_key_env": bool(os.environ.get("TWELVE_DATA_KEY")),
        "twelve_data_key_env_length": len(os.environ.get("TWELVE_DATA_KEY", "")),
        "oanda_key_set": bool(s.oanda_api_key),
        "anthropic_key_set": bool(s.anthropic_api_key),
        "environment": s.environment,
    }
