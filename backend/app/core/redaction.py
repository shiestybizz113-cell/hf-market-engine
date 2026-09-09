"""Small public-response redaction helpers for provenance metadata."""

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def safe_source_reference(value: Any) -> Any:
    """Strip URL credentials/query/fragment while preserving source identity."""
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = urlsplit(value)
    except Exception:
        return value
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return value

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def scrub_public_sources(value: Any) -> Any:
    """Recursively redact source_reference fields in API response structures."""
    if isinstance(value, list):
        return [scrub_public_sources(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "source_reference":
                out[key] = safe_source_reference(item)
            else:
                out[key] = scrub_public_sources(item)
        return out
    return value
