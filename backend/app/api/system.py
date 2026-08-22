from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.core import ai
from app.core.config import settings
from app.core.database import get_db
from app.core.plans import catalog_public
from app.models.schemas import PlanInfo, SystemHealth

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=SystemHealth)
async def health(current_user=Depends(get_current_user)):
    """Authenticated operator health — no global customer/business counts."""
    db_status = "ok"
    try:
        db = get_db()
        await db.command("ping")
    except Exception:
        db_status = "error"

    # Do not turn a demo-mode operator dashboard into a recurring external ping.
    if settings.MARKET_DATA_MODE == "demo":
        cg_status = "demo"
    else:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get("https://api.coingecko.com/api/v3/ping")
                cg_status = "ok" if response.status_code == 200 else "degraded"
        except Exception:
            cg_status = "error"

    # Keep the existing response contract but scope usage counters to the current
    # operator. `active_users=1` means this authenticated session, not company
    # registration/traction data.
    saved_strategies = 0
    paper_trades = 0
    if db_status == "ok":
        try:
            db = get_db()
            saved_strategies = await db.strategies.count_documents({"user_id": current_user["_id"]})
            paper_trades = await db.paper_trades.count_documents({"user_id": current_user["_id"]})
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
        active_users=1,
        saved_strategies=saved_strategies,
        paper_trades=paper_trades,
    )


@router.get("/pricing/plans", response_model=list[PlanInfo])
async def pricing_plans():
    return [PlanInfo(**p) for p in catalog_public()]
