#!/usr/bin/env python3
"""
Billing preflight — can this deployment actually take money?

Checks every link in the chain between a user clicking Upgrade and their
plan flipping to paid. Reports exactly what is missing and what to do
about it. Read-only: creates nothing, charges nothing, modifies nothing.

    cd backend && python scripts/billing_preflight.py

Exit code 0 if the chain is complete, 1 if any blocking gap remains.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.core.plans import PLAN_CATALOG  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
OK, FAIL, WARN = f"{GREEN}PASS{RESET}", f"{RED}BLOCK{RESET}", f"{YELLOW}WARN{RESET}"

blocking = 0
warnings = 0


def check(label: str, passed: bool, fix: str = "", blocking_gap: bool = True) -> bool:
    global blocking, warnings
    if passed:
        print(f"  [{OK}]  {label}")
        return True
    if blocking_gap:
        blocking += 1
        print(f"  [{FAIL}] {label}")
    else:
        warnings += 1
        print(f"  [{WARN}]  {label}")
    if fix:
        print(f"         {DIM}{fix}{RESET}")
    return False


print("\nBILLING PREFLIGHT — hf-market-engine")
print("=" * 62)

# ---------------------------------------------------------------- API key
print("\n1. Stripe API key")

key = settings.STRIPE_SECRET_KEY or ""
has_key = check(
    "STRIPE_SECRET_KEY is set",
    bool(key) and "replace_me" not in key,
    "Stripe Dashboard > Developers > API keys. Set STRIPE_SECRET_KEY in .env",
)

if has_key:
    is_live = key.startswith("sk_live_")
    is_test = key.startswith("sk_test_")
    check(
        f"Key mode: {'LIVE' if is_live else 'TEST' if is_test else 'UNRECOGNIZED'}",
        is_live or is_test,
        "Key should start with sk_live_ or sk_test_",
    )
    if is_live:
        print(f"         {YELLOW}Live key: real cards, real charges.{RESET}")

# --------------------------------------------------------------- Price IDs
print("\n2. Stripe Price IDs — one per paid tier")

price_map = {
    "pro": settings.STRIPE_PRICE_PRO,
    "advanced": settings.STRIPE_PRICE_ADVANCED,
    "team": settings.STRIPE_PRICE_TEAM,
    "white_label": settings.STRIPE_PRICE_WHITELABEL,
}

paid_plans = [p for p in PLAN_CATALOG if p["id"] != "free"]

for plan in paid_plans:
    pid = plan["id"]
    val = price_map.get(pid) or ""
    env_name = f"STRIPE_PRICE_{'WHITELABEL' if pid == 'white_label' else pid.upper()}"
    label = f"{plan['name']:<20} ${plan['price_monthly']:>5}/mo  {env_name}"
    check(
        label,
        val.startswith("price_") and "replace" not in val,
        f"Create a recurring monthly ${plan['price_monthly']} price in Stripe, "
        f"then set {env_name}",
    )

# ---------------------------------------------------------------- Webhook
print("\n3. Webhook — flips the user to paid after checkout")

check(
    "STRIPE_WEBHOOK_SECRET is set",
    bool(settings.STRIPE_WEBHOOK_SECRET)
    and "replace_me" not in settings.STRIPE_WEBHOOK_SECRET,
    "Without this, a customer can pay and stay on the free plan. "
    "Stripe Dashboard > Developers > Webhooks > add endpoint "
    "POST /api/billing/webhook, subscribe to checkout.session.completed, "
    "then copy the signing secret (whsec_...)",
)

# ------------------------------------------------------------ Redirect URLs
print("\n4. Post-checkout redirects")

for name, url in (
    ("STRIPE_SUCCESS_URL", settings.STRIPE_SUCCESS_URL),
    ("STRIPE_CANCEL_URL", settings.STRIPE_CANCEL_URL),
):
    is_local = "localhost" in url or "127.0.0.1" in url
    check(
        f"{name} points at a public URL",
        bool(url) and not is_local,
        f"Currently '{url}'. Customers cannot reach localhost.",
        blocking_gap=(settings.ENVIRONMENT.lower() == "production"),
    )

# ------------------------------------------------------------ Live reachability
print("\n5. Stripe connectivity")

if has_key:
    try:
        import stripe

        stripe.api_key = key
        acct = stripe.Account.retrieve()
        check(f"Reached Stripe account {acct.get('id')}", True)

        found = 0
        for pid, val in price_map.items():
            if not (val or "").startswith("price_"):
                continue
            try:
                pr = stripe.Price.retrieve(val)
                amount = (pr.get("unit_amount") or 0) / 100
                recurring = pr.get("recurring") or {}
                expected = next(p["price_monthly"] for p in paid_plans if p["id"] == pid)
                check(
                    f"{pid:<12} {val}  ${amount:,.0f}/{recurring.get('interval', '?')}",
                    pr.get("active") and amount == expected
                    and recurring.get("interval") == "month",
                    f"Expected an active recurring monthly price of ${expected}",
                )
                found += 1
            except Exception as e:
                check(f"{pid:<12} {val}", False, f"Stripe rejected this ID: {e}")
        if found == 0:
            print(f"         {DIM}No Price IDs set yet — nothing to verify.{RESET}")
    except ImportError:
        check("stripe package installed", False, "pip install stripe", blocking_gap=False)
    except Exception as e:
        check("Stripe API reachable", False, str(e))

# ------------------------------------------------------------------ Verdict
print("\n" + "=" * 62)

if blocking == 0:
    print(f"{GREEN}CHAIN COMPLETE — this deployment can collect payment.{RESET}")
    print("\nVerify end to end before trusting it:")
    print("  1. Sign up a fresh account; confirm plan is 'free'")
    print("  2. POST /api/billing/checkout with {\"plan_id\": \"pro\"}")
    print("  3. Complete checkout")
    print("  4. GET /api/auth/me and confirm plan is now 'pro'")
    print("  5. Hit a gated endpoint and confirm it no longer refuses")
    print(f"\n  {DIM}Step 4 is the one that catches a missing webhook.{RESET}")
    sys.exit(0)

print(f"{RED}{blocking} blocking gap(s) — checkout will fail or not upgrade.{RESET}")
if warnings:
    print(f"{YELLOW}{warnings} warning(s).{RESET}")
print("\nNothing is collected until every BLOCK above is cleared.")
sys.exit(1)
