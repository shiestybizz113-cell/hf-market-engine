import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import (
    assets,
    auth,
    billing,
    capital,
    compute,
    decision,
    energy,
    evidence,
    execution,
    hardware,
    infrastructure,
    journal,
    market,
    mining,
    system,
    trading,
)
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.infrastructure_data import close_infrastructure_cache
from app.core.rate_limit import (
    check_rate_limit,
    close_rate_limit_client,
    limiter,
    rate_limit_handler,
)
from app.core.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()
    await close_rate_limit_client()
    await close_infrastructure_cache()


app = FastAPI(
    title="hf-market-engine",
    description=(
        "AI Trading Intelligence OS for Crypto, Stocks, ETFs, Forex, Macro & DeFi.\n\n"
        "Research, simulation and AI-assisted analysis only. "
        "No real trading. No real spend. All proposals and evidence-backed."
    ),
    lifespan=lifespan,
)

# CORS
if settings.CORS_ORIGINS:
    origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
else:
    origins = ["http://localhost:3000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware (slowapi)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def public_edge_controls(request: Request, call_next):
    """Trace every request and enforce shared public rate limits."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    allowed, limit = await check_rate_limit(request)
    if not allowed:
        response = JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "request_id": request_id,
                "retry_after_seconds": limit.get("window_seconds", 60),
            },
        )
        response.headers["Retry-After"] = str(limit.get("window_seconds", 60))
    else:
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    if limit.get("limit") is not None:
        response.headers["X-RateLimit-Limit"] = str(limit["limit"])
        response.headers["X-RateLimit-Remaining"] = str(limit.get("remaining", 0))
    if limit.get("degraded"):
        response.headers["X-RateLimit-Degraded"] = "1"
    return response


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(mining.router, prefix="/api")
app.include_router(decision.router, prefix="/api")
app.include_router(capital.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(hardware.router, prefix="/api")
app.include_router(energy.router, prefix="/api")
app.include_router(compute.router, prefix="/api")
app.include_router(infrastructure.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "product": "hf-market-engine",
        "tagline": "AI Trading Intelligence OS",
        "phase": "1 – Research & Simulation",
        "disclaimer": (
            "This platform provides market research, simulation, and AI-assisted analysis. "
            "It is not financial advice and does not guarantee profits. "
            "Trading crypto, stocks, ETFs, forex and other assets involves substantial risk."
        ),
    }


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "service": settings.APP_NAME}
