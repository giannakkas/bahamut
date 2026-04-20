from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
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
from bahamut.ws.admin_live import router as admin_ws_router
from bahamut.paper_trading.router import router as paper_trading_router
from bahamut.scanner.router import router as scanner_router
from bahamut.stress.router import router as stress_router
from bahamut.readiness.router import router as readiness_router
from bahamut.portfolio.router import router as portfolio_router
from bahamut.admin.router import router as admin_router
from bahamut.system.router import router as system_router
from bahamut.intelligence.router import router as trust_router
from bahamut.shared.redis_client import redis_manager

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Bahamut.AI", environment=settings.environment)
    await redis_manager.connect()
    # Initialize all database tables (centralized schema management)
    try:
        from bahamut.db.schema.tables import init_schema
        init_schema()
    except Exception as e:
        logger.error("schema_init_failed", error=str(e))
    # Ensure super admin role for allowed emails
    try:
        from bahamut.db.query import run_transaction
        from bahamut.auth.permissions import SUPER_ADMIN_EMAILS
        for email in SUPER_ADMIN_EMAILS:
            run_transaction(
                "UPDATE users SET role = 'super_admin' WHERE email = :e AND role != 'super_admin'",
                {"e": email}
            )
        logger.info("super_admin_check_complete")
    except Exception as e:
        logger.debug("super_admin_promotion_skipped", error=str(e))
    # Update existing portfolios to current max_open_positions default
    try:
        from bahamut.db.query import run_transaction
        run_transaction(
            "UPDATE paper_portfolios SET max_open_positions = 10 WHERE max_open_positions < 10",
            {}
        )
    except Exception as e:
        logger.debug("portfolio_max_positions_update_skipped", error=str(e))
    # Load persisted threshold overrides
    try:
        from bahamut.learning.thresholds import load_persisted_thresholds
        load_persisted_thresholds()
    except Exception as e:
        logger.debug("threshold_load_skipped", error=str(e))
    # Clear stale cached data from previous deploy
    if redis_manager.redis:
        try:
            await redis_manager.redis.delete("bahamut:daily_brief")
            logger.info("cleared_stale_brief_cache")
        except Exception as e:
            logger.warning("stale_cache_clear_failed", error=str(e))

    # ── Production safety: register shutdown handlers ──
    try:
        from bahamut.execution.shutdown import register_shutdown_handlers, startup_reconciliation
        register_shutdown_handlers()
        # Check for unclean shutdown from previous deploy
        startup_reconciliation()
    except Exception as e:
        logger.warning("production_safety_init_skipped", error=str(e)[:100])

    # ── Production safety: initialize order manager tables ──
    try:
        from bahamut.execution.order_manager import OrderManager
        OrderManager()  # triggers idempotent table creation
        logger.info("order_manager_initialized")
    except Exception as e:
        logger.warning("order_manager_init_skipped", error=str(e)[:100])

    # ── Warm exchange filters so diagnostics show loaded state after deploy ──
    try:
        from bahamut.execution.exchange_filters import refresh_filters
        ef = refresh_filters()
        if ef:
            logger.info("exchange_filters_warmed_on_startup", count=len(ef))
    except Exception as e:
        logger.warning("exchange_filters_startup_warm_failed", error=str(e)[:100])

    yield

    # Shutdown
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


# ── CORS: config-driven allowed origins ──
def _get_allowed_origins() -> list[str]:
    """Build allowed origins from settings. Never allow bare '*' in production."""
    origins = list(settings.cors_origins)
    # Always allow the configured frontend URL
    if settings.frontend_url and settings.frontend_url not in origins:
        origins.append(settings.frontend_url)
    # Always allow localhost for dev
    dev_origins = [
        "http://localhost:3000", "http://localhost:3001",
        "http://127.0.0.1:3000", "http://127.0.0.1:3001",
    ]
    for o in dev_origins:
        if o not in origins:
            origins.append(o)
    # Strip wildcard — never allow * in production
    origins = [o for o in origins if o != "*"]
    if not origins:
        # Fail-safe: at least allow the known frontend
        origins = ["https://frontend-production-947b.up.railway.app", "https://bahamut.ai"]
    return origins


_allowed_origins = _get_allowed_origins()
logger.info("cors_configured", origins=_allowed_origins)


def _origin_allowed(origin: str | None) -> str | None:
    """Return the origin if it's in the allowed list, else None."""
    if not origin:
        return None
    for allowed in _allowed_origins:
        if origin == allowed:
            return origin
    return None


class CORSAlwaysMiddleware(BaseHTTPMiddleware):
    """Add CORS headers even on 500 errors, but only for allowed origins."""
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origin = _origin_allowed(origin)
        cors_headers = {}
        if allowed_origin:
            cors_headers = {
                "Access-Control-Allow-Origin": allowed_origin,
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }

        if request.method == "OPTIONS":
            return JSONResponse(content={}, headers=cors_headers)

        try:
            response = await call_next(request)
            for k, v in cors_headers.items():
                response.headers[k] = v
            return response
        except Exception as e:
            logger.error("unhandled_error", error=str(e), traceback=traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers=cors_headers,
            )


app.add_middleware(CORSAlwaysMiddleware)

# Observability: request IDs, slow request tracking, structured logging
from bahamut.middleware.observability import ObservabilityMiddleware
app.add_middleware(ObservabilityMiddleware)

# Routes
from bahamut.middleware.metrics import router as metrics_router

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
app.include_router(admin_ws_router, tags=["admin-ws"])
app.include_router(paper_trading_router, prefix="/api/v1", tags=["paper-trading"])
app.include_router(scanner_router, prefix="/api/v1", tags=["scanner"])
app.include_router(stress_router, prefix="/api/v1/stress", tags=["stress-testing"])
app.include_router(readiness_router, prefix="/api/v1/readiness", tags=["readiness"])
app.include_router(portfolio_router, prefix="/api/v1/portfolio", tags=["portfolio-intel"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(system_router, prefix="/api/v1/system", tags=["system"])
app.include_router(trust_router, prefix="/api/v1/trust", tags=["trust"])
app.include_router(metrics_router, tags=["metrics"])

# Monitoring dashboard + notification settings
try:
    from bahamut.monitoring.dashboard_api import router as monitoring_router
    app.include_router(monitoring_router, prefix="/api/v1/monitoring", tags=["monitoring"])
except Exception:
    pass
try:
    from bahamut.monitoring.settings_api import router as settings_router
    app.include_router(settings_router, prefix="/api/v1/monitoring", tags=["monitoring"])
except Exception:
    pass
try:
    from bahamut.trading.router import router as training_router
    app.include_router(training_router, prefix="/api/v1/training", tags=["training"])
except Exception:
    pass

try:
    from bahamut.wallet.router import router as wallet_router
    app.include_router(wallet_router, prefix="/api/v1/wallet", tags=["wallet"])
except Exception:
    pass


@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    import time as _time
    checks: dict[str, bool] = {}

    # DB connectivity
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:
        checks["db"] = False

    # Redis connectivity
    try:
        if redis_manager.redis:
            await redis_manager.redis.ping()
            checks["redis"] = True
        else:
            checks["redis"] = False
    except Exception:
        checks["redis"] = False

    # Training loop freshness (last cycle < 2x interval = 1200s)
    try:
        if redis_manager.redis:
            ts_raw = await redis_manager.redis.get("bahamut:training:last_cycle_ts")
            if ts_raw:
                age = _time.time() - int(ts_raw)
                checks["training_freshness"] = age < 1200
            else:
                checks["training_freshness"] = False
        else:
            checks["training_freshness"] = False
    except Exception:
        checks["training_freshness"] = False

    # Shutdown state
    try:
        from bahamut.execution.shutdown import is_shutting_down
        checks["shutdown"] = not is_shutting_down()
    except Exception:
        checks["shutdown"] = True

    # Circuit breakers (per-platform)
    try:
        from bahamut.execution.circuit_breaker import circuit_breaker_binance, circuit_breaker_alpaca
        bin_ok = circuit_breaker_binance.get_status()["state"] == "CLOSED"
        alp_ok = circuit_breaker_alpaca.get_status()["state"] == "CLOSED"
        checks["circuit_breaker"] = bin_ok and alp_ok
    except Exception:
        checks["circuit_breaker"] = True

    failed = [name for name, ok in checks.items() if not ok]
    status = "healthy" if not failed else "degraded"
    status_code = 200 if not failed else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={
            "status": status,
            "service": "bahamut-api",
            "version": "1.0.0",
            "environment": settings.environment,
            "checks": checks,
            "failed": failed,
        },
        status_code=status_code,
    )


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
    """Debug endpoint — gated behind admin auth in production."""
    if settings.environment == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "environment": settings.environment,
        "note": "Detailed debug info removed for security. Use /api/v1/readiness/check.",
    }
