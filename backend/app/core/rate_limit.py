"""Shared request-rate limiting for public deployment.

Production uses Redis so all Uvicorn workers see the same counters. Development
fails open when Redis is unavailable so local work does not require the cache.
The limiter never stores request bodies, tokens, email addresses, or evidence.
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from redis.asyncio import Redis

from app.core.config import settings


@dataclass(frozen=True)
class Limit:
    requests: int
    window_seconds: int


# Tightest limits are on unauthenticated auth routes and expensive Capital
# operations. Read-only proof/data browsing gets a larger budget.
ROUTE_LIMITS = {
    "/api/auth/login": Limit(20, 60),
    "/api/auth/register": Limit(10, 60),
    "/api/capital/run": Limit(30, 60),
    "/api/capital/scenarios": Limit(15, 60),
    "/api/capital/optimize": Limit(15, 60),
    "/api/hardware/offers": Limit(60, 60),
    "/api/compute/offers": Limit(60, 60),
    "/api/energy/prices": Limit(60, 60),
}
DEFAULT_API_LIMIT = Limit(180, 60)

_redis: Optional[Redis] = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


def _identity(request: Request) -> str:
    """Pseudonymous counter key: IP hash + authenticated bearer fingerprint.

    We intentionally do not persist the raw IP or token. The short digest is
    only used inside expiring Redis counters.
    """
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "unknown")
    auth = request.headers.get("authorization", "")
    material = f"{ip}|{auth[:80]}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def _limit_for(path: str) -> Limit:
    if path in ROUTE_LIMITS:
        return ROUTE_LIMITS[path]
    if path.startswith("/api/evidence/") or path.startswith("/api/assets"):
        return Limit(120, 60)
    return DEFAULT_API_LIMIT


async def check_rate_limit(request: Request) -> tuple[bool, dict]:
    """Return (allowed, metadata). Development fails open on Redis errors."""
    if not request.url.path.startswith("/api/"):
        return True, {}
    if request.url.path in ("/api/live", "/api/ready", "/api/health"):
        return True, {}

    limit = _limit_for(request.url.path)
    bucket = int(time.time()) // limit.window_seconds
    key = f"rl:{request.url.path}:{_identity(request)}:{bucket}"

    try:
        redis = _client()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, limit.window_seconds + 5)
        remaining = max(0, limit.requests - int(count))
        return int(count) <= limit.requests, {
            "limit": limit.requests,
            "remaining": remaining,
            "window_seconds": limit.window_seconds,
        }
    except Exception:
        # Production compose waits for Redis health before the backend starts;
        # fail-open here avoids turning a transient cache problem into an outage.
        return True, {"degraded": True}


async def close_rate_limit_client() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
