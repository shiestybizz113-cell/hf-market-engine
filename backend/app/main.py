import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    auth, billing, capital, decision, evidence, execution, infrastructure,
    journal, market, mining, system, trading,
)
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.rate_limit import check_rate_limit, close_rate_limit_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_rate_limit_client()
    await close_mongo_connection()


app = FastAPI(
    title="hf-market-engine",
    description=(
        "Capital + Compute Intelligence Infrastructure. Evidence-backed market, "
        "mining, compute, energy and capital-allocation research. Read-only; "
        "the Capital optimizer proposes and never executes."
    ),
    version="0.2.0-capital-v2",
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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
        response.headers["X-RateLimit-State"] = "degraded"
    return response


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
app.include_router(infrastructure.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "product": "hf-market-engine",
        "tagline": "Capital + Compute Intelligence Infrastructure",
        "phase": "Capital Command Center V2",
        "read_only": True,
        "disclaimer": (
            "Research, simulation and AI-assisted capital intelligence. Not financial "
            "advice. The Capital optimizer proposes only and cannot trade, spend or deploy."
        ),
    }


@app.get("/api/live")
async def liveness():
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/api/ready")
async def readiness():
    try:
        await get_db().command("ping")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "status": "ready",
        "service": settings.APP_NAME,
        "market_data_mode": settings.MARKET_DATA_MODE,
    }


@app.get("/api/health")
async def api_health():
    """Compatibility health route; now checks the shared datastore."""
    try:
        await get_db().command("ping")
        database = "ok"
    except Exception:
        database = "error"
    if database != "ok":
        raise HTTPException(status_code=503, detail={"status": "degraded", "database": database})
    return {"status": "ok", "service": settings.APP_NAME, "database": database}
