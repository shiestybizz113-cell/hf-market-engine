"""
Billing API — Stripe Checkout (test + live) + plan catalog.

Test mode:
  Use sk_test_ keys and price IDs from Stripe Dashboard → Test mode.
  Webhook: stripe listen --forward-to localhost:8000/api/billing/webhook

Dev without Stripe:
  POST /api/billing/dev-upgrade (disabled when ENVIRONMENT=production)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
from datetime import datetime, timezone
from app.api.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.plans import catalog_public
from pydantic import BaseModel

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class DevUpgradeRequest(BaseModel):
    plan_id: str


def _stripe_mode(secret_key: str) -> str:
    if not secret_key:
        return "unconfigured"
    if secret_key.startswith("sk_test_"):
        return "test"
    if secret_key.startswith("sk_live_"):
        return "live"
    return "unknown"


def _get_stripe():
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            503,
            "Stripe not configured. Set STRIPE_SECRET_KEY (sk_test_... for test mode) "
            "or use POST /api/billing/dev-upgrade in development.",
        )
    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        raise HTTPException(503, "stripe package not installed — pip install stripe")


@router.get("/status")
async def billing_status():
    mode = _stripe_mode(settings.STRIPE_SECRET_KEY)
    prices = {
        "pro": bool(settings.STRIPE_PRICE_PRO),
        "advanced": bool(settings.STRIPE_PRICE_ADVANCED),
        "team": bool(settings.STRIPE_PRICE_TEAM),
        "white_label": bool(settings.STRIPE_PRICE_WHITELABEL),
    }
    return {
        "stripe_mode": mode,
        "checkout_ready": mode in ("test", "live") and any(prices.values()),
        "prices_configured": prices,
        "webhook_configured": bool(settings.STRIPE_WEBHOOK_SECRET),
        "dev_upgrade_enabled": settings.ENVIRONMENT.lower() != "production",
    }


@router.get("/plans")
async def list_plans():
    return catalog_public()


@router.get("/me")
async def my_billing(current_user=Depends(get_current_user)):
    db = get_db()
    user = await db.users.find_one({"_id": current_user["_id"]})
    return {
        "plan": user.get("plan", "free"),
        "stripe_customer_id": user.get("stripe_customer_id"),
        "stripe_subscription_id": user.get("stripe_subscription_id"),
        "plan_updated_at": user.get("plan_updated_at"),
        "stripe_mode": _stripe_mode(settings.STRIPE_SECRET_KEY),
    }


@router.post("/checkout")
async def create_checkout(payload: CheckoutRequest, current_user=Depends(get_current_user)):
    plan_id = payload.plan_id.lower()
    if plan_id not in ("pro", "advanced", "team", "white_label"):
        raise HTTPException(400, "Invalid plan_id")

    stripe = _get_stripe()
    mode = _stripe_mode(settings.STRIPE_SECRET_KEY)

    price_map = {
        "pro": settings.STRIPE_PRICE_PRO,
        "advanced": settings.STRIPE_PRICE_ADVANCED,
        "team": settings.STRIPE_PRICE_TEAM,
        "white_label": settings.STRIPE_PRICE_WHITELABEL,
    }
    price_id = price_map.get(plan_id)
    if not price_id:
        raise HTTPException(
            503,
            f"Stripe Price ID not set for plan '{plan_id}'. "
            f"In Stripe Dashboard ({mode} mode) create a recurring Price, then set "
            f"STRIPE_PRICE_{plan_id.upper()} in .env",
        )

    db = get_db()
    user = await db.users.find_one({"_id": current_user["_id"]})
    customer_id = user.get("stripe_customer_id")

    if not customer_id:
        customer = stripe.Customer.create(
            email=user["email"],
            metadata={"user_id": user["_id"], "app": "hf-market-engine"},
        )
        customer_id = customer["id"]
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"stripe_customer_id": customer_id}},
        )

    success = payload.success_url or settings.STRIPE_SUCCESS_URL
    cancel = payload.cancel_url or settings.STRIPE_CANCEL_URL

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success + ("&" if "?" in success else "?") + "session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel,
        metadata={"user_id": user["_id"], "plan_id": plan_id},
        subscription_data={"metadata": {"user_id": user["_id"], "plan_id": plan_id}},
        allow_promotion_codes=True,
    )
    return {"url": session.url, "session_id": session.id, "mode": mode}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "STRIPE_WEBHOOK_SECRET not configured")

    stripe = _get_stripe()
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(400, f"Webhook signature verification failed: {e}")

    db = get_db()
    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id = (data.get("metadata") or {}).get("user_id")
        plan_id = (data.get("metadata") or {}).get("plan_id", "pro")
        sub_id = data.get("subscription")
        if user_id:
            await db.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "plan": plan_id,
                        "stripe_subscription_id": sub_id,
                        "plan_updated_at": datetime.now(timezone.utc),
                    }
                },
            )

    elif etype in ("customer.subscription.deleted", "customer.subscription.updated"):
        status = data.get("status")
        user_id = (data.get("metadata") or {}).get("user_id")
        if not user_id:
            sub_id = data.get("id")
            if sub_id:
                user_doc = await db.users.find_one({"stripe_subscription_id": sub_id})
                user_id = user_doc["_id"] if user_doc else None
        if user_id and status in ("canceled", "unpaid", "incomplete_expired"):
            await db.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "plan": "free",
                        "plan_updated_at": datetime.now(timezone.utc),
                    }
                },
            )

    return {"received": True, "type": etype}


@router.post("/dev-upgrade")
async def dev_upgrade(payload: DevUpgradeRequest, current_user=Depends(get_current_user)):
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(403, "dev-upgrade disabled in production")

    from app.core.plans import PLAN_RANK
    plan_id = payload.plan_id.lower()
    if plan_id not in PLAN_RANK:
        raise HTTPException(400, f"Unknown plan: {plan_id}")

    db = get_db()
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "plan": plan_id,
                "plan_updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return {"ok": True, "plan": plan_id, "message": f"Dev upgraded to {plan_id}"}
