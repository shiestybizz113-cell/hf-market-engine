import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
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
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.infrastructure_data import close_infrastructure_cache
from app.core.rate_limit import check_rate_limit, close_rate_limit_client


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
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
    )


# Routers
app.include_router(auth.router)
app.include_router(market.router)
app.include_router(trading.router)
app.include_router(system.router)
app.include_router(execution.router)
app.include_router(journal.router)
app.include_router(billing.router)
app.include_router(evidence.router)
app.include_router(mining.router)
app.include_router(decision.router)
app.include_router(capital.router)
app.include_router(assets.router)
app.include_router(hardware.router)
app.include_router(energy.router)
app.include_router(compute.router)
app.include_router(infrastructure.router)


@app.get("/")
async def root():
    return {"message": "hf-market-engine API"}
