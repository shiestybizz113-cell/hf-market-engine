"""
Security headers middleware.

Applies defense-in-depth HTTP headers to every response.
Values are conservative and appropriate for an API + SPA deployment.

HSTS is only sent when ENVIRONMENT=production, since forcing HTTPS
on localhost breaks local development.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking — this API is not meant to be framed
        response.headers["X-Frame-Options"] = "DENY"

        # Limit referrer leakage to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable browser features this app never uses
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        # Content Security Policy — API responses are JSON, so lock it down.
        # The SPA is served separately and has its own CSP.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )

        # HSTS — production only. Forces HTTPS for 1 year including subdomains.
        if settings.ENVIRONMENT.lower() == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
