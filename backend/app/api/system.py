from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.core.budget import spend_summary
from app.core.database import get_db
from app.core.plans import catalog_public
from app.models.schemas import PlanInfo, SystemHealth

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=SystemHealth)
async def health(current_user=Depends(get_current_user)):
    """Authenticated operator health — no global customer/business counts."""
    db_status = "ok"
    cg_status = "unknown"
    try:
        db = get_db()
        await db.command("ping")
    except Exception:
        db_status = "error"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.coingecko.com/api/v3/ping", timeout=5)
            if resp.status_code == 200:
                cg_status = "ok"
    except Exception:
        cg_status = "error"

    return SystemHealth(
        status="ok",
        timestamp=datetime.now(UTC),
        database=db_status,
        coingecko=cg_status
    )


@router.get("/system/plans", response_model=list[PlanInfo])
async def plans():
    """Public plan catalog (no auth required)."""
    return catalog_public()


@router.get("/system/spend")
async def ai_spend(current_user=Depends(get_current_user)):
    """
    Rolling 24h AI spend against the enforced caps.

    Computed from the signed receipt ledger — the same append-only record
    an auditor reads. Spend evidence and spend enforcement cannot disagree,
    because they are the same data.
    """
    return await spend_summary(get_db(), user_id=current_user["_id"])


@router.get("/pricing/plans", response_model=list[PlanInfo])
async def pricing_plans():
    """Public plan catalog (no auth required)."""
    return catalog_public()
