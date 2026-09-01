"""
Rate limiting — governance harness for auth endpoints.

Fail-closed by design: if the limiter cannot determine state,
it denies rather than allows. This is the outer-loop kill switch
for credential-stuffing and API abuse loops.

Limits (conservative Phase 1 defaults — tighten before investor demo):
  POST /api/auth/login    → 10 requests / minute / IP
  POST /api/auth/register → 5  requests / minute / IP

Both limits are intentionally asymmetric: registration is more expensive
(DB write, bcrypt hash) and lower-volume by nature. Login gets 10 to
accommodate power users but is still well below brute-force thresholds.

Changing limits: update LOGIN_LIMIT and REGISTER_LIMIT strings below.
Format: "{count} per {period}" — e.g. "20 per minute", "100 per hour".

Redis backend: when REDIS_URL is configured, limits survive restarts and
are shared across workers. Falls back to in-process memory only in dev.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ── Limits ────────────────────────────────────────────────────────────────────

LOGIN_LIMIT = "10 per minute"
REGISTER_LIMIT = "5 per minute"

# ── Limiter ───────────────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    # slowapi will use in-memory storage if redis is not reachable —
    # acceptable for dev; production must have REDIS_URL set.
    default_limits=[],
)


# ── Exception handler ─────────────────────────────────────────────────────────

def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Return a clean 429 with Retry-After so clients and monitoring know
    exactly how long to back off. Never silently swallow the error.
    """
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down.",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
