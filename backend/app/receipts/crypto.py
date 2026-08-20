"""
Canonicalization + signing for Empire-1 receipts.

Non-repudiation only works if two parties can independently arrive at the
exact same bytes to hash and sign. This module owns that contract:
canonical_json() is the single source of truth for "what does this
receipt actually mean, as bytes."
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from .schema import Integrity, Receipt, SignatureAlgorithm


def canonical_json(data: dict[str, Any]) -> bytes:
    """
    Deterministic serialization: sorted keys, no insignificant whitespace,
    UTF-8. Any two implementations that receive the same logical data
    produce identical bytes here — that's what makes the hash and
    signature portable and independently verifiable.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(data: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(data)).hexdigest()
    return f"sha256:{digest}"


class SigningKey:
    """
    Wraps an Ed25519 keypair with the key_id that goes into
    integrity.signer_public_key_id. In production this key material lives
    in a KMS/HSM, never in app config — this class exists so the *call
    site* (sign/verify) never has to know or care where the bytes live.
    """

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey | None = None):
        self.key_id = key_id
        self.private_key = private_key or Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    @property
    def public_key_bytes(self) -> bytes:
        from cryptography.hazmat.primitives import serialization

        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign_receipt(self, receipt: Receipt) -> Receipt:
        """Returns a NEW Receipt with integrity populated. Never mutates in place —
        a signed receipt is a distinct artifact from its draft."""
        unsigned = receipt.unsigned_dict()
        digest = canonical_hash(unsigned)
        signature = self.private_key.sign(digest.encode("utf-8"))

        signed = receipt.model_copy(deep=True)
        signed.integrity = Integrity(
            canonical_hash=digest,
            signature=signature.hex(),
            signer_public_key_id=self.key_id,
            signature_algorithm=SignatureAlgorithm.ED25519,
        )
        return signed


class KeyRegistry:
    """
    Minimal public-key directory: key_id -> Ed25519PublicKey.
    A real deployment backs this with the PKI receipt chain itself
    (key_rotation / key_revocation receipts) — this class is intentionally
    dumb so that logic stays visible in registry.py rather than hidden here.
    """

    def __init__(self):
        self._keys: dict[str, Ed25519PublicKey] = {}

    def register(self, key_id: str, public_key: Ed25519PublicKey) -> None:
        self._keys[key_id] = public_key

    def get(self, key_id: str) -> Ed25519PublicKey:
        if key_id not in self._keys:
            raise KeyError(f"Unknown signer key_id: {key_id!r}")
        return self._keys[key_id]


def verify_receipt(receipt: Receipt, registry: KeyRegistry) -> tuple[bool, str]:
    """
    Independently re-derives the canonical hash and checks the signature.
    Returns (is_valid, reason) — reason is human-readable so a verification
    failure in a demo or a UI can say WHY, not just fail silently.
    """
    if receipt.integrity is None:
        return False, "receipt has no integrity block — was never signed"

    recomputed_hash = canonical_hash(receipt.unsigned_dict())
    if recomputed_hash != receipt.integrity.canonical_hash:
        return False, (
            "canonical hash mismatch — the receipt's content does not match "
            "what was signed. This is what tampering looks like."
        )

    try:
        public_key = registry.get(receipt.integrity.signer_public_key_id)
    except KeyError as e:
        return False, str(e)

    try:
        public_key.verify(
            bytes.fromhex(receipt.integrity.signature),
            receipt.integrity.canonical_hash.encode("utf-8"),
        )
    except InvalidSignature:
        return False, "signature does not verify against the claimed signer's public key"

    return True, "signature and hash both verify"
