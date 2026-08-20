"""
Archisynapse v1.1 — Cryptographic primitives.

Ed25519 signing and SHA-256 hashing for tamper-evident receipts.

Key lifecycle:
  - One keypair per deployment, generated once on first startup.
  - Private key lives in ARCHISYNAPSE_SIGNING_KEY env var (hex).
  - Public key is embedded in every receipt for offline verification.
  - Key rotation: add new key, re-sign new receipts, old keys remain
    valid for historical receipt verification.

No key = no signing = receipts not persisted. This is intentional:
a receipt without a signature is worthless as evidence.
"""

import hashlib
import json
import os
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)


# ── Key management ─────────────────────────────────────────────────────────────

_private_key: Optional[Ed25519PrivateKey] = None
_public_key_hex: Optional[str] = None


def _load_or_generate_key() -> Tuple[Ed25519PrivateKey, str]:
    """Load signing key from env, or generate an ephemeral one for dev."""
    global _private_key, _public_key_hex

    if _private_key is not None:
        return _private_key, _public_key_hex

    raw_hex = ""
    try:
        from app.core.config import settings
        raw_hex = settings.ARCHISYNAPSE_SIGNING_KEY or ""
    except Exception:
        # Settings unavailable (e.g. standalone key-gen script) — fall back to env
        raw_hex = os.environ.get("ARCHISYNAPSE_SIGNING_KEY", "")

    if raw_hex:
        try:
            raw_bytes = bytes.fromhex(raw_hex)
            key = Ed25519PrivateKey.from_private_bytes(raw_bytes)
        except Exception as e:
            raise RuntimeError(
                f"ARCHISYNAPSE_SIGNING_KEY is set but invalid: {e}"
            ) from e
    else:
        # Dev fallback — ephemeral key, not persisted across restarts.
        # Receipts signed with ephemeral key cannot be verified offline
        # across restarts. Production MUST set ARCHISYNAPSE_SIGNING_KEY.
        import logging
        logging.getLogger("archisynapse").warning(
            "ARCHISYNAPSE_SIGNING_KEY not set — using ephemeral signing key. "
            "Historical receipt verification will fail after restart. "
            "Set ARCHISYNAPSE_SIGNING_KEY in production."
        )
        key = Ed25519PrivateKey.generate()

    pub_bytes = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_hex = pub_bytes.hex()

    _private_key = key
    _public_key_hex = pub_hex
    return key, pub_hex


def get_public_key_hex() -> str:
    _, pub = _load_or_generate_key()
    return pub


def generate_signing_key_hex() -> str:
    """Generate a new Ed25519 private key. Print and set as env var."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return raw.hex()


# ── Hashing ───────────────────────────────────────────────────────────────────

def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: dict) -> str:
    """Deterministic JSON: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ── Signing ───────────────────────────────────────────────────────────────────

def sign(payload_json: str) -> Tuple[str, str]:
    """
    Sign canonical payload JSON with Ed25519.
    Returns (signature_hex, public_key_hex).
    """
    key, pub_hex = _load_or_generate_key()
    sig_bytes = key.sign(payload_json.encode("utf-8"))
    return sig_bytes.hex(), pub_hex


def verify(payload_json: str, signature_hex: str, public_key_hex: str) -> bool:
    """
    Verify an Ed25519 signature against the canonical payload JSON.
    Returns True if valid, False otherwise. Never raises.
    """
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(signature_hex)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(sig_bytes, payload_json.encode("utf-8"))
        return True
    except Exception:
        return False
