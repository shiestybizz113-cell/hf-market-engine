from fastapi import APIRouter
from datetime import datetime, timezone
from app.models.schemas import SystemHealth, PlanInfo
from app.core.database import get_db
from app.core.config import settings
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

    return SystemHealth(
        status="operational" if db_status == "ok" else "degraded",
        api="ok",
        database=db_status,
        coingecko=cg_status,
        ai="template",  # Phase 1 rule-based
        auth="ok",
        last_market_refresh=datetime.now(timezone.utc),
        active_users=active_users,
        saved_strategies=strategies,
        paper_trades=paper,
    )


@router.get("/pricing/plans", response_model=list[PlanInfo])
async def pricing_plans():
    return [
        PlanInfo(
            id="free",
            name="Free",
            price_monthly=0,
            features=[
                "Basic multi-asset dashboard",
                "Watchlist up to 10 assets",
                "3 AI summaries per day",
                "Demo signals only",
                "Manual portfolio tracker",
            ],
            ai_reviews_per_month=3,
            max_watchlist=10,
        ),
        PlanInfo(
            id="pro",
            name="Pro Trader",
            price_monthly=settings.PLAN_PRO_PRICE,
            features=[
                "Crypto, stock & ETF dashboards",
                "AI Signal Engine",
                "Strategy Builder",
                "Paper Trading",
                "Trade Journal",
                "Basic Backtesting",
                "Portfolio / P&L Tracker",
                "75 AI reviews / month",
            ],
            ai_reviews_per_month=75,
            max_watchlist=999,
        ),
        PlanInfo(
            id="advanced",
            name="Advanced Trader",
            price_monthly=settings.PLAN_ADVANCED_PRICE,
            features=[
                "Everything in Pro",
                "Cross-Asset Correlation Radar",
                "Alpha Scanner",
                "Advanced Backtesting",
                "AI Strategy Council",
                "Risk Engine",
                "Macro Regime Dashboard",
                "Weekly performance reports",
                "300 AI reviews / month",
            ],
            ai_reviews_per_month=300,
            max_watchlist=999,
        ),
        PlanInfo(
            id="team",
            name="Team / Community",
            price_monthly=settings.PLAN_TEAM_PRICE,
            features=[
                "Everything in Advanced",
                "5 team seats",
                "Shared strategy library",
                "Community watchlists",
                "Shared paper-trading workspace",
                "Team reports & admin controls",
                "1,500 AI reviews / month",
            ],
            ai_reviews_per_month=1500,
            max_watchlist=999,
            seats=5,
        ),
        PlanInfo(
            id="whitelabel",
            name="White Label",
            price_monthly=settings.PLAN_WHITELABEL_MONTHLY,
            setup_fee=settings.PLAN_WHITELABEL_SETUP,
            features=[
                "Branded multi-asset trading terminal",
                "Custom logo & domain",
                "Private community dashboard",
                "Up to 1,000 users",
                "White-label reports",
                "Admin controls & billing hooks",
            ],
            ai_reviews_per_month=5000,
            max_watchlist=999,
            seats=1000,
        ),
    ]
