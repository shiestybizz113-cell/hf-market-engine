from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.database import connect_to_mongo, close_mongo_connection
from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_handler
from app.core.security_headers import SecurityHeadersMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.api import auth, market, trading, system, execution, journal, billing, evidence, mining, decision, capital
from app.api import hardware, compute, energy, assets


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="hf-market-engine",
    description=(
        "AI Trading Intelligence OS for Crypto, Stocks, ETFs, Forex, Macro & DeFi.\n\n"
        "Research, simulation and AI-assisted analysis only. "
        "Not financial advice. Does not guarantee profits. "
        "Trading involves substantial risk."
    ),
    version="0.1.0-phase1",
    lifespan=lifespan,
)

# ── Rate-limit harness ────────────────────────────────────────────────────────
# Outer-loop enforcement: limiter state attached to app so SlowAPIMiddleware
# can find it. Exception handler returns clean 429s instead of 500s.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# ─────────────────────────────────────────────────────────────────────────────

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Development fallback only — main.py refuses to start without CORS_ORIGINS in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
app.include_router(hardware.router, prefix="/api")
app.include_router(compute.router, prefix="/api")
app.include_router(energy.router, prefix="/api")
app.include_router(assets.router, prefix="/api")


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
