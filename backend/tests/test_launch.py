"""
Launch-readiness tests.

These verify the governance and security guarantees that gate production
deployment. A failure here is a launch blocker, not a bug.
"""

import pytest
from httpx import AsyncClient

from app.core.archisynapse import build_receipt, verify_receipt
from app.core.archisynapse.schema import SignedReceipt


# ══════════════════════════════════════════════════════════════════════════════
# Security headers
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient):
    """Every response carries defense-in-depth headers."""
    r = await client.get("/api/health")
    h = r.headers

    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in h
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]


@pytest.mark.asyncio
async def test_hsts_absent_in_non_production(client: AsyncClient):
    """
    HSTS must NOT be sent outside production — it would force HTTPS
    on localhost and break local development for a year.
    """
    r = await client.get("/api/health")
    assert "Strict-Transport-Security" not in r.headers


# ══════════════════════════════════════════════════════════════════════════════
# Receipt signing — Archisynapse v1.1
# ══════════════════════════════════════════════════════════════════════════════

def test_receipt_signature_valid():
    """A freshly built receipt verifies against its own signature."""
    receipt = build_receipt(
        job="test_job",
        system_prompt="You are a test analyst.",
        user_prompt="Analyze TEST.",
        output="Test output.",
        model="gpt-4o-mini",
        provider_name="openai",
        fallback_used=False,
        user_id="launch_test_user",
    )
    assert verify_receipt(receipt) is True


def test_receipt_tamper_detected():
    """Mutating the signed payload invalidates the signature."""
    receipt = build_receipt(
        job="test_job",
        system_prompt="You are a test analyst.",
        user_prompt="Analyze TEST.",
        output="Test output.",
        model="gpt-4o-mini",
        provider_name="openai",
        fallback_used=False,
        user_id="launch_test_user",
    )

    tampered = SignedReceipt(
        payload=receipt.payload,
        payload_json=receipt.payload_json.replace("gpt-4o-mini", "gpt-9000"),
        signature=receipt.signature,
        public_key=receipt.public_key,
    )
    assert verify_receipt(tampered) is False


def test_receipt_hashes_are_content_bound():
    """Different inputs produce different hashes — no collision shortcuts."""
    a = build_receipt(
        job="j", system_prompt="s", user_prompt="u1", output="o",
        model="gpt-4o-mini", provider_name="openai", fallback_used=False,
    )
    b = build_receipt(
        job="j", system_prompt="s", user_prompt="u2", output="o",
        model="gpt-4o-mini", provider_name="openai", fallback_used=False,
    )
    assert a.payload.input_hash != b.payload.input_hash
    assert a.payload.output_hash == b.payload.output_hash  # same output


def test_receipt_ids_unique():
    """Every receipt gets a distinct UUID."""
    ids = {
        build_receipt(
            job="j", system_prompt="s", user_prompt="u", output="o",
            model="gpt-4o-mini", provider_name="openai", fallback_used=False,
        ).payload.receipt_id
        for _ in range(50)
    }
    assert len(ids) == 50


# ══════════════════════════════════════════════════════════════════════════════
# Evidence API — public key + offline verify
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_public_key_endpoint(client: AsyncClient):
    """Deployment public key is retrievable without auth for auditors."""
    r = await client.get("/api/evidence/public-key")
    assert r.status_code == 200
    body = r.json()
    assert body["algorithm"] == "Ed25519"
    assert len(body["public_key"]) == 64  # 32 bytes hex


@pytest.mark.asyncio
async def test_offline_verify_endpoint_accepts_valid(client: AsyncClient):
    """A valid receipt verifies through the public verify endpoint."""
    receipt = build_receipt(
        job="verify_test", system_prompt="s", user_prompt="u", output="o",
        model="gpt-4o-mini", provider_name="openai", fallback_used=False,
    )
    r = await client.post("/api/evidence/verify", json={
        "payload_json": receipt.payload_json,
        "signature": receipt.signature,
        "public_key": receipt.public_key,
    })
    assert r.status_code == 200
    assert r.json()["signature_valid"] is True


@pytest.mark.asyncio
async def test_offline_verify_endpoint_rejects_tampered(client: AsyncClient):
    """A tampered payload is rejected through the public verify endpoint."""
    receipt = build_receipt(
        job="verify_test", system_prompt="s", user_prompt="u", output="o",
        model="gpt-4o-mini", provider_name="openai", fallback_used=False,
    )
    r = await client.post("/api/evidence/verify", json={
        "payload_json": receipt.payload_json.replace("openai", "evil"),
        "signature": receipt.signature,
        "public_key": receipt.public_key,
    })
    assert r.status_code == 200
    assert r.json()["signature_valid"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Production config guards
# ══════════════════════════════════════════════════════════════════════════════

def test_production_requires_signing_key(monkeypatch):
    """Production must refuse to boot without a stable signing key."""
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("MONGODB_URL", "mongodb://u:p@mongo:27017")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ARCHISYNAPSE_SIGNING_KEY", "")

    with pytest.raises(Exception, match="ARCHISYNAPSE_SIGNING_KEY"):
        Settings()


def test_production_rejects_wildcard_cors(monkeypatch):
    """Production must refuse a wildcard CORS origin."""
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("MONGODB_URL", "mongodb://u:p@mongo:27017")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("ARCHISYNAPSE_SIGNING_KEY", "a" * 64)

    with pytest.raises(Exception, match="CORS_ORIGINS"):
        Settings()


def test_production_rejects_weak_secret(monkeypatch):
    """Production must refuse a short SECRET_KEY."""
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("MONGODB_URL", "mongodb://u:p@mongo:27017")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ARCHISYNAPSE_SIGNING_KEY", "a" * 64)

    with pytest.raises(Exception, match="SECRET_KEY"):
        Settings()


def test_invalid_market_data_mode_rejected(monkeypatch):
    """MARKET_DATA_MODE accepts only 'demo' or 'live' — nothing else."""
    from app.core.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_DATA_MODE", "synthetic")

    with pytest.raises(Exception, match="MARKET_DATA_MODE"):
        Settings()
