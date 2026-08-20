"""
Spend enforcement and alerting tests.

These verify HARNESS.md §4 kill conditions are enforcement, not observability.
A failure here means a runaway loop could bill unbounded.
"""

import pytest

from app.core import budget


# ── Fake ledger ───────────────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, total):
        self._total = total
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return {"_id": None, "total": self._total}


class _FakeCollection:
    def __init__(self, user_total, global_total):
        self.user_total = user_total
        self.global_total = global_total

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        scoped = "user_id" in match
        return _FakeCursor(self.user_total if scoped else self.global_total)


class FakeDB:
    """Minimal stand-in for the receipt ledger."""
    def __init__(self, user_total=0.0, global_total=0.0):
        self._coll = _FakeCollection(user_total, global_total)

    def __getitem__(self, name):
        return self._coll


class BrokenDB:
    def __getitem__(self, name):
        raise RuntimeError("ledger unavailable")


# ── Enforcement ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_under_caps_allowed():
    d = await budget.check_budget(FakeDB(0.10, 1.00), user_id="u1")
    assert d.allowed
    assert d.blocked is False
    assert d.user_spend_usd == 0.10
    assert d.global_spend_usd == 1.00


@pytest.mark.asyncio
async def test_user_cap_blocks():
    """Per-user cap (default $2.00) must block, not warn."""
    d = await budget.check_budget(FakeDB(2.50, 5.00), user_id="u1")
    assert d.blocked
    assert "Per-user" in d.reason


@pytest.mark.asyncio
async def test_global_cap_blocks():
    """Global cap (default $50.00) protects the account across all users."""
    d = await budget.check_budget(FakeDB(0.01, 55.00), user_id="u1")
    assert d.blocked
    assert "Global" in d.reason


@pytest.mark.asyncio
async def test_global_cap_takes_precedence():
    """When both caps are breached, the global reason is reported."""
    d = await budget.check_budget(FakeDB(99.0, 99.0), user_id="u1")
    assert d.blocked
    assert "Global" in d.reason


@pytest.mark.asyncio
async def test_missing_ledger_fails_closed():
    """No ledger means no accounting — block rather than bill blind."""
    d = await budget.check_budget(None, user_id="u1")
    assert d.blocked
    assert "failing closed" in d.reason.lower()


@pytest.mark.asyncio
async def test_ledger_error_fails_closed():
    """A ledger read failure must block, not silently allow."""
    d = await budget.check_budget(BrokenDB(), user_id="u1")
    assert d.blocked
    assert "failing closed" in d.reason.lower()


@pytest.mark.asyncio
async def test_decision_is_immutable():
    """BudgetDecision is frozen — a gate result cannot be edited after the fact."""
    d = await budget.check_budget(FakeDB(0.0, 0.0), user_id="u1")
    with pytest.raises(Exception):
        d.allowed = True


# ── Spend summary ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spend_summary_shape():
    s = await budget.spend_summary(FakeDB(0.50, 10.00), user_id="u1")
    assert s["available"] is True
    assert s["window"] == "24h"
    assert s["user"]["spend_usd"] == 0.50
    assert s["user"]["pct_used"] == 25.0      # 0.50 / 2.00
    assert s["global"]["pct_used"] == 20.0    # 10.00 / 50.00
    assert s["user"]["remaining_usd"] == 1.50


@pytest.mark.asyncio
async def test_spend_summary_handles_broken_ledger():
    s = await budget.spend_summary(BrokenDB(), user_id="u1")
    assert s["available"] is False


@pytest.mark.asyncio
async def test_spend_endpoint_requires_auth(client):
    r = await client.get("/api/system/spend")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_spend_endpoint_authenticated(auth_client):
    r = await auth_client.get("/api/system/spend")
    assert r.status_code == 200
    body = r.json()
    assert "user" in body
    assert "global" in body
    assert "enforcement_enabled" in body


# ── Alerting ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_never_raises_without_webhook():
    """Log-only posture is valid; alerting must not break the request path."""
    from app.core import alerting
    await alerting.fire(
        alerting.RECEIPT_WRITE_FAILED,
        "test message",
        context={"job": "test"},
    )


@pytest.mark.asyncio
async def test_alert_never_raises_on_bad_webhook(monkeypatch):
    """A dead webhook must not propagate an exception to the caller."""
    from app.core import alerting
    monkeypatch.setattr(
        alerting.settings, "ALERT_WEBHOOK_URL", "http://127.0.0.1:1/nope"
    )
    alerting._last_sent.clear()
    await alerting.fire(alerting.BUDGET_EXCEEDED, "test", context={})


@pytest.mark.asyncio
async def test_alert_dedupe(monkeypatch):
    """Repeated alerts of the same type are deduped inside the interval."""
    from app.core import alerting
    monkeypatch.setattr(alerting.settings, "ALERT_WEBHOOK_URL", "http://example.invalid")
    monkeypatch.setattr(alerting.settings, "ALERT_MIN_INTERVAL_SECONDS", 300)
    alerting._last_sent.clear()

    assert alerting._should_send(alerting.BUDGET_EXCEEDED) is True
    assert alerting._should_send(alerting.BUDGET_EXCEEDED) is False
    # Different type is not deduped by the first
    assert alerting._should_send(alerting.SIGNATURE_INVALID) is True
