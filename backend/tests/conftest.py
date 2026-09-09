"""
Test fixtures for hf-market-engine.

Strategy:
- Override MongoDB with a test database (wiped between test sessions)
- Override MARKET_DATA_MODE=demo (non-negotiable in tests; never live)
- Use FastAPI's async test client (httpx-based)
- No real API keys required; all market data comes from DemoProvider

The test DB is the real MongoDB service (spun up by CI or local docker-compose).
Tests use a separate DB name (hf_test) so they never touch production data.
"""

import os
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Force test environment before any app imports
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MARKET_DATA_MODE", "demo")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-exactly!")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "hf_test")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

from app.main import app
from app.core.database import connect_to_mongo, close_mongo_connection, get_db
from app.core.rate_limit import limiter


@pytest_asyncio.fixture()
async def _mongo():
    """Connect to test MongoDB per test, wipe DB on teardown.

    NOT autouse — only connected when a test requests client/auth_client.
    Function-scoped so Motor's loop matches the per-test ASGITransport loop
    (avoids the BaseHTTPMiddleware loop-hopping RuntimeError).
    """
    await connect_to_mongo()
    yield
    db = get_db()
    await db.client.drop_database("hf_test")
    await close_mongo_connection()
    limiter.reset()


@pytest_asyncio.fixture()
async def client(_mongo) -> AsyncClient:
    """Fresh async test client per test.  Depends on _mongo for DB setup."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest_asyncio.fixture()
async def auth_client(client: AsyncClient) -> AsyncClient:
    """Authenticated test client — registers + logs in a fresh user."""
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass1!"

    reg = await client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "CI User",
    })
    assert reg.status_code == 200, f"Register failed: {reg.text}"

    login = await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"

    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture()
async def auth_client(client: AsyncClient) -> AsyncClient:
    """Authenticated test client — registers + logs in a fresh user."""
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass1!"

    reg = await client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "CI User",
    })
    assert reg.status_code == 200, f"Register failed: {reg.text}"

    login = await client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"

    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
