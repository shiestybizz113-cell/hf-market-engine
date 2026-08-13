from fastapi import APIRouter
from datetime import datetime, timezone
from app.models.schemas import SystemHealth, PlanInfo
from app.core.database import get_db
from app.core.config import settings
from app.core.plans import catalog_public
from app.core import ai
import httpx

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=SystemHealth)
async def health():
    db_status = "ok"
    cg_status = "unknown"
    try:
        db = get_db()
        await db.command("ping")
    except Exception:
        db_status = "error"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.coingecko.com/api/v3/ping")
            cg_status = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        cg_status = "error"

    active_users = 0
    strategies = 0
    paper = 0
    try:
        db = get_db()
        active_users = await db.users.count_documents({})
        strategies = await db.strategies.count_documents({})
        paper = await db.paper_trades.count_documents({})
    except Exception:
        pass

    ai_info = ai.provider_info()

    return SystemHealth(
        status="operational" if db_status == "ok" else "degraded",
        api="ok",
        database=db_status,
        coingecko=cg_status,
        ai=ai_info["provider"],
        ai_model=ai_info["model"],
        market_data_mode=settings.MARKET_DATA_MODE,
        auth="ok",
        last_market_refresh=datetime.now(timezone.utc),
        active_users=active_users,
        saved_strategies=strategies,
        paper_trades=paper,
    )


@router.get("/pricing/plans", response_model=list[PlanInfo])
async def pricing_plans():
    return [PlanInfo(**p) for p in catalog_public()]

