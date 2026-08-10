"""
Plan catalog + entitlement helpers.

Phase 1: plan stored on user document; gates enforced in API.
Stripe Checkout upgrades plan via webhook (or dev upgrade endpoint).
"""

from typing import Dict, List
from fastapi import HTTPException, Depends
from app.api.auth import get_current_user

PLAN_RANK = {
    "free": 0,
    "pro": 1,
    "advanced": 2,
    "team": 3,
    "white_label": 4,
}

PLAN_CATALOG: List[Dict] = [
    {
        "id": "free",
        "name": "Free",
        "price_monthly": 0,
        "setup_fee": 0,
        "features": [
            "Dashboard & market overview",
            "Watchlist (10 assets)",
            "Basic signals (limited)",
            "Correlation radar (read-only)",
        ],
        "ai_reviews_per_month": 5,
        "max_watchlist": 10,
        "seats": 1,
    },
    {
        "id": "pro",
        "name": "Pro Trader",
        "price_monthly": 59,
        "setup_fee": 0,
        "features": [
            "Everything in Free",
            "Paper trading",
            "Strategy Lab",
            "Backtesting",
            "AI Strategy Council",
            "Risk engine",
            "Journal",
            "Watchlist 50 assets",
        ],
        "ai_reviews_per_month": 100,
        "max_watchlist": 50,
        "seats": 1,
    },
    {
        "id": "advanced",
        "name": "Advanced Trader",
        "price_monthly": 199,
        "setup_fee": 0,
        "features": [
            "Everything in Pro",
            "Execution research + sim algos",
            "Higher signal volume",
            "Priority data refresh",
            "Watchlist 200 assets",
        ],
        "ai_reviews_per_month": 500,
        "max_watchlist": 200,
        "seats": 1,
    },
    {
        "id": "team",
        "name": "Team / Community",
        "price_monthly": 699,
        "setup_fee": 0,
        "features": [
            "Everything in Advanced",
            "5 seats",
            "Shared watchlists (roadmap)",
            "Admin seat management",
        ],
        "ai_reviews_per_month": 2000,
        "max_watchlist": 500,
        "seats": 5,
    },
    {
        "id": "white_label",
        "name": "White Label",
        "price_monthly": 1499,
        "setup_fee": 5000,
        "features": [
            "Branded terminal",
            "Custom domain (Phase 2 runtime)",
            "Seat pool",
            "Dedicated support path",
        ],
        "ai_reviews_per_month": 10000,
        "max_watchlist": 2000,
        "seats": 25,
    },
]

FEATURE_MIN_PLAN: Dict[str, str] = {
    "paper_trading": "pro",
    "backtesting": "pro",
    "strategy_lab": "pro",
    "ai_council": "pro",
    "risk_engine": "pro",
    "journal": "pro",
    "execution_sim": "advanced",
}


def plan_rank(plan: str) -> int:
    return PLAN_RANK.get((plan or "free").lower(), 0)


def has_feature(user_plan: str, feature: str) -> bool:
    required = FEATURE_MIN_PLAN.get(feature, "free")
    return plan_rank(user_plan) >= plan_rank(required)


def require_plan(min_plan: str):
    async def _dep(current_user=Depends(get_current_user)):
        user_plan = current_user.get("plan", "free")
        if plan_rank(user_plan) < plan_rank(min_plan):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {min_plan} plan or higher. Current plan: {user_plan}. Upgrade at /pricing.",
            )
        return current_user
    return _dep


def require_feature(feature: str):
    async def _dep(current_user=Depends(get_current_user)):
        user_plan = current_user.get("plan", "free")
        if not has_feature(user_plan, feature):
            need = FEATURE_MIN_PLAN.get(feature, "pro")
            raise HTTPException(
                status_code=403,
                detail=f"Feature '{feature}' requires {need}+. Current plan: {user_plan}.",
            )
        return current_user
    return _dep


def catalog_public() -> List[Dict]:
    return PLAN_CATALOG
