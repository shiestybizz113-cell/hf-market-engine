from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.database import connect_to_mongo, close_mongo_connection
from app.core.config import settings
from app.api import auth, market, trading, system, execution, journal, billing


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
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
