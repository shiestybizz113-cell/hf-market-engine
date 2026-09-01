"""
AI spend enforcement.

HARNESS.md §4 kill condition, implemented as enforcement rather than
observability. When a budget cap is hit, the AI call is BLOCKED and the
caller receives the rule-based fallback instead. The loop actually stops.

Two caps, both rolling 24h, both computed from the signed receipt ledger:
  - Per-user   (AI_BUDGET_USER_DAILY_USD)
  - Global     (AI_BUDGET_GLOBAL_DAILY_USD)

Why the receipt ledger is the source of truth: it is the same append-only
record an auditor would read. Spend enforcement and spend evidence cannot
disagree, because they are the same data.

Fail-closed on the global cap: if the ledger cannot be read, assume the
budget is spent and block. A silent unbounded loop is worse than a
temporarily degraded one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.core import alerting
from app.core.config import settings

log = logging.getLogger("governance.budget")

COLLECTION = "analysis_receipts"
_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BudgetDecision:
    """Result of a pre-flight budget check. Frozen — no post-hoc mutation."""
    allowed: bool
    reason: str | None = None
    user_spend_usd: float = 0.0
    global_spend_usd: float = 0.0
    user_cap_usd: float = 0.0
    global_cap_usd: float = 0.0

    @property
    def blocked(self) -> bool:
        return not self.allowed


async def _spend_since(db, cutoff: float, user_id: str | None = None) -> float:
    """Sum estimated_cost_usd from the receipt ledger since cutoff."""
    match: dict = {"generated_at": {"$gte": cutoff}}
    if user_id is not None:
        match["user_id"] = user_id

    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$estimated_cost_usd"}}},
    ]
    cursor = db[COLLECTION].aggregate(pipeline)
    async for row in cursor:
        return float(row.get("total") or 0.0)
    return 0.0


async def check_budget(db, user_id: str | None = None) -> BudgetDecision:
    """
    Pre-flight budget check. Call before any paid AI inference.

    Returns BudgetDecision. If .blocked is True, the caller MUST NOT make
    the API call and should return its fallback instead.
    """
    user_cap = settings.AI_BUDGET_USER_DAILY_USD
    global_cap = settings.AI_BUDGET_GLOBAL_DAILY_USD

    if db is None:
        # No ledger = no accounting = fail closed on spend.
        return BudgetDecision(
            allowed=False,
            reason="Spend ledger unavailable — failing closed.",
            user_cap_usd=user_cap,
            global_cap_usd=global_cap,
        )

    cutoff = time.time() - _WINDOW_SECONDS

    try:
        global_spend = await _spend_since(db, cutoff)
        user_spend = (
            await _spend_since(db, cutoff, user_id=user_id)
            if user_id is not None
            else 0.0
        )
    except Exception as exc:
        log.error("Budget check failed to read ledger: %s", exc)
        return BudgetDecision(
            allowed=False,
            reason="Spend ledger read failed — failing closed.",
            user_cap_usd=user_cap,
            global_cap_usd=global_cap,
        )

    # Global cap first — it protects the account, not just one user.
    if global_cap > 0 and global_spend >= global_cap:
        reason = (
            f"Global 24h AI budget reached: "
            f"${global_spend:.4f} / ${global_cap:.2f}"
        )
        await alerting.fire(
            alerting.BUDGET_EXCEEDED,
            reason,
            context={
                "scope": "global",
                "spend_usd": round(global_spend, 4),
                "cap_usd": global_cap,
                "window": "24h",
            },
        )
        return BudgetDecision(
            allowed=False,
            reason=reason,
            user_spend_usd=user_spend,
            global_spend_usd=global_spend,
            user_cap_usd=user_cap,
            global_cap_usd=global_cap,
        )

    if user_id is not None and user_cap > 0 and user_spend >= user_cap:
        reason = (
            f"Per-user 24h AI budget reached: "
            f"${user_spend:.4f} / ${user_cap:.2f}"
        )
        await alerting.fire(
            alerting.BUDGET_EXCEEDED,
            reason,
            context={
                "scope": "user",
                "user_id": user_id,
                "spend_usd": round(user_spend, 4),
                "cap_usd": user_cap,
                "window": "24h",
            },
        )
        return BudgetDecision(
            allowed=False,
            reason=reason,
            user_spend_usd=user_spend,
            global_spend_usd=global_spend,
            user_cap_usd=user_cap,
            global_cap_usd=global_cap,
        )

    return BudgetDecision(
        allowed=True,
        user_spend_usd=user_spend,
        global_spend_usd=global_spend,
        user_cap_usd=user_cap,
        global_cap_usd=global_cap,
    )


async def spend_summary(db, user_id: str | None = None) -> dict:
    """Read-only spend snapshot for the /system/spend endpoint."""
    cutoff = time.time() - _WINDOW_SECONDS
    try:
        global_spend = await _spend_since(db, cutoff)
        user_spend = (
            await _spend_since(db, cutoff, user_id=user_id)
            if user_id is not None
            else 0.0
        )
    except Exception:
        return {"available": False, "reason": "Ledger read failed"}

    user_cap = settings.AI_BUDGET_USER_DAILY_USD
    global_cap = settings.AI_BUDGET_GLOBAL_DAILY_USD

    return {
        "available": True,
        "window": "24h",
        "enforcement_enabled": settings.AI_BUDGET_ENFORCE,
        "user": {
            "spend_usd": round(user_spend, 6),
            "cap_usd": user_cap,
            "pct_used": round(user_spend / user_cap * 100, 1) if user_cap > 0 else None,
            "remaining_usd": round(max(0.0, user_cap - user_spend), 6) if user_cap > 0 else None,
        },
        "global": {
            "spend_usd": round(global_spend, 6),
            "cap_usd": global_cap,
            "pct_used": round(global_spend / global_cap * 100, 1) if global_cap > 0 else None,
            "remaining_usd": round(max(0.0, global_cap - global_spend), 6) if global_cap > 0 else None,
        },
    }
