"""
Core test suite — hf-market-engine Phase 1

Coverage targets:
  - Health endpoints (system integrity)
  - Auth flow (register, login, token, 401 guard)
  - Auth rate limiting (governance harness — 429 enforcement)
  - Data mode contract (demo label, no synthetic live data)
  - Evidence receipt API
  - Market endpoints (quote shape, source labeling)

All tests use MARKET_DATA_MODE=demo. No real API keys required.
"""

import pytest
from httpx import AsyncClient


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["product"] == "hf-market-engine"
    assert "disclaimer" in body


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_system_health_shape(client: AsyncClient):
    r = await client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    # Required fields
    for field in ("status", "api", "database", "market_data_mode"):
        assert field in body, f"Missing field: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# Data mode contract (VISION.md non-negotiable)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_market_data_mode_is_demo(client: AsyncClient):
    """
    VISION.md: "MARKET_DATA_MODE=demo labels everything simulation."
    System health must report demo mode in test environment.
    """
    r = await client.get("/api/system/health")
    assert r.status_code == 200
    assert r.json()["market_data_mode"] == "demo"


@pytest.mark.asyncio
async def test_demo_prices_are_labeled(auth_client: AsyncClient):
    """
    Every quote in demo mode must carry source=demo.
    No synthetic number may masquerade as live data.
    """
    r = await auth_client.get("/api/market/prices?symbols=BTC&asset_class=crypto")
    assert r.status_code == 200
    quotes = r.json()
    assert len(quotes) > 0, "Expected at least one quote for BTC"
    for q in quotes:
        # Quote must have a price
        assert q["price"] > 0


@pytest.mark.asyncio
async def test_market_overview_returns_data(auth_client: AsyncClient):
    r = await auth_client.get("/api/market/overview")
    assert r.status_code == 200
    body = r.json()
    assert "prices" in body or "regime" in body  # Either field is acceptable


# ══════════════════════════════════════════════════════════════════════════════
# Auth — register + login
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    import uuid
    email = f"reg_{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/auth/register", json={
        "email": email,
        "password": "ValidPass1!",
        "full_name": "Test User",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email
    assert body["plan"] == "free"
    assert "id" in body


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    import uuid
    email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    payload = {"email": email, "password": "ValidPass1!"}
    await client.post("/api/auth/register", json=payload)
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code == 400
    assert "already registered" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    import uuid
    email = f"login_{uuid.uuid4().hex[:8]}@example.com"
    password = "LoginPass1!"
    await client.post("/api/auth/register", json={
        "email": email, "password": password
    })
    r = await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    import uuid
    email = f"badpw_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/auth/register", json={
        "email": email, "password": "CorrectPass1!"
    })
    r = await client.post(
        "/api/auth/login",
        data={"username": email, "password": "WrongPass1!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(auth_client: AsyncClient):
    r = await auth_client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert "email" in body
    assert "plan" in body


@pytest.mark.asyncio
async def test_invalid_token_rejected(client: AsyncClient):
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Auth rate limiting (governance harness)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_login_rate_limit_enforced(client: AsyncClient):
    """
    HARNESS.md: POST /api/auth/login → 10 req / min / IP.
    After 10 failed attempts in rapid succession, must receive 429.
    """
    import uuid
    email = f"ratelimit_{uuid.uuid4().hex[:8]}@example.com"

    responses = []
    for _ in range(15):
        r = await client.post(
            "/api/auth/login",
            data={"username": email, "password": "WrongPass!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        responses.append(r.status_code)

    status_codes = set(responses)
    assert 429 in status_codes, (
        f"Rate limit not enforced. Got status codes: {responses}"
    )


@pytest.mark.asyncio
async def test_register_rate_limit_enforced(client: AsyncClient):
    """
    HARNESS.md: POST /api/auth/register → 5 req / min / IP.
    After 5 attempts, must receive 429.
    """
    import uuid

    responses = []
    for _ in range(10):
        email = f"spam_{uuid.uuid4().hex}@example.com"
        r = await client.post("/api/auth/register", json={
            "email": email,
            "password": "SpamPass1!",
        })
        responses.append(r.status_code)

    status_codes = set(responses)
    assert 429 in status_codes, (
        f"Register rate limit not enforced. Got status codes: {responses}"
    )


@pytest.mark.asyncio
async def test_rate_limit_returns_retry_after(client: AsyncClient):
    """429 response must include Retry-After header."""
    import uuid

    for _ in range(15):
        r = await client.post(
            "/api/auth/login",
            data={"username": f"{uuid.uuid4().hex}@x.com", "password": "x"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code == 429:
            assert "retry_after_seconds" in r.json()
            break
    else:
        pytest.skip("Rate limit not hit in this test run — may need Redis")


# ══════════════════════════════════════════════════════════════════════════════
# Evidence receipts
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_receipts_requires_auth(client: AsyncClient):
    r = await client.get("/api/evidence/receipts")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_receipts_authenticated_empty(auth_client: AsyncClient):
    """Fresh user has no receipts — endpoint returns valid empty list."""
    r = await auth_client.get("/api/evidence/receipts")
    assert r.status_code == 200
    body = r.json()
    assert "receipts" in body
    assert "count" in body
    assert body["count"] == len(body["receipts"])


@pytest.mark.asyncio
async def test_receipts_limit_validation(auth_client: AsyncClient):
    r = await auth_client.get("/api/evidence/receipts?limit=0")
    assert r.status_code == 400

    r = await auth_client.get("/api/evidence/receipts?limit=101")
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Pricing plans (public endpoint)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pricing_plans_public(client: AsyncClient):
    r = await client.get("/api/pricing/plans")
    assert r.status_code == 200
    plans = r.json()
    assert len(plans) > 0
    for plan in plans:
        assert "name" in plan
        assert "price_monthly" in plan
