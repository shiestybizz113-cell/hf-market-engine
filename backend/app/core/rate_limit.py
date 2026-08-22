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
    """Pseudonymous counter key: trusted-edge IP + bearer fingerprint.

    Caddy overwrites X-Real-IP from the actual remote peer before proxying. We
    intentionally do NOT trust arbitrary client X-Forwarded-For values here.
    The digest is only used inside expiring Redis counters.
    """
    edge_ip = request.headers.get("x-real-ip", "").strip()
    ip = edge_ip or (request.client.host if request.client else "unknown")
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
        # Production compose waits for Redis health before backend startup; a
        # transient cache outage degrades rate limiting instead of taking the
        # entire read-only intelligence product down.
        return True, {"degraded": True}


async def close_rate_limit_client() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
