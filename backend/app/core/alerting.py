"""
Governance alerting.

Fires on the events HARNESS.md says must not pass silently:
  - BUDGET_EXCEEDED       — an AI spend cap was hit and a call was blocked
  - RECEIPT_WRITE_FAILED  — a signed receipt could not be persisted
  - SIGNATURE_INVALID     — a stored receipt failed verification (tampering)
  - DEMO_DATA_IN_LIVE     — demo-sourced quote appeared in a live session

Design:
  - Never raises. An alerting failure must not break the request path.
  - Deduped per alert type to avoid flooding during an incident.
  - Always logs, even when no webhook is configured. Log-only is a valid
    deployment posture; silence is not.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger("governance.alert")

# alert_type -> last sent monotonic timestamp
_last_sent: dict[str, float] = {}


# ── Alert types ───────────────────────────────────────────────────────────────

BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
RECEIPT_WRITE_FAILED = "RECEIPT_WRITE_FAILED"
SIGNATURE_INVALID = "SIGNATURE_INVALID"
DEMO_DATA_IN_LIVE = "DEMO_DATA_IN_LIVE"

_SEVERITY = {
    BUDGET_EXCEEDED: "warning",
    RECEIPT_WRITE_FAILED: "critical",
    SIGNATURE_INVALID: "critical",
    DEMO_DATA_IN_LIVE: "critical",
}


def _should_send(alert_type: str) -> bool:
    """Dedupe: at most one webhook per alert type per interval."""
    now = time.monotonic()
    last = _last_sent.get(alert_type)
    interval = settings.ALERT_MIN_INTERVAL_SECONDS
    if last is not None and (now - last) < interval:
        return False
    _last_sent[alert_type] = now
    return True


async def fire(
    alert_type: str,
    message: str,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Record a governance alert. Always logs. Pushes to webhook if configured
    and not deduped. Never raises.
    """
    severity = _SEVERITY.get(alert_type, "warning")
    ctx = context or {}

    # Always log — this is the floor, webhook is the ceiling.
    log_line = f"[{severity.upper()}] {alert_type}: {message} | {ctx}"
    if severity == "critical":
        log.error(log_line)
    else:
        log.warning(log_line)

    if not settings.ALERT_WEBHOOK_URL:
        return

    if not _should_send(alert_type):
        return

    payload = {
        "text": f":rotating_light: *{alert_type}* ({severity})\n{message}",
        "attachments": [
            {
                "color": "danger" if severity == "critical" else "warning",
                "fields": [
                    {"title": k, "value": str(v), "short": True}
                    for k, v in ctx.items()
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(settings.ALERT_WEBHOOK_URL, json=payload)
    except Exception as exc:
        # Alerting failure must never break the request path.
        log.error("Alert webhook failed for %s: %s", alert_type, exc)
