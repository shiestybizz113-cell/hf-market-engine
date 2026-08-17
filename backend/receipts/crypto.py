from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .schema import Integrity, Receipt


def canonical_receipt_bytes(receipt: Receipt) -> bytes:
    """Canonical JSON for the immutable signed envelope, excluding integrity itself."""
    payload = receipt.model_dump(mode="json", exclude={"integrity"})
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SigningKey:
    def __init__(self, key_id: str, private_key_b64: Optional[str] = None):
        self.key_id = key_id
        if private_key_b64:
            raw = base64.b64decode(private_key_b64)
            self._private_key = Ed25519PrivateKey.from_private_bytes(raw)
        else:
            self._private_key = Ed25519PrivateKey.generate()

    @property
    def public_key(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    @property
    def private_key_b64(self) -> str:
        raw = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return base64.b64encode(raw).decode("ascii")

    def sign_receipt(self, receipt: Receipt) -> Receipt:
        signed = receipt.model_copy(deep=True)
        signed.integrity = None
        canonical = canonical_receipt_bytes(signed)
        signature = self._private_key.sign(canonical)
        signed.integrity = Integrity(
            content_hash_sha256=sha256_hex(canonical),
            signature_ed25519=base64.b64encode(signature).decode("ascii"),
            signer_public_key_id=self.key_id,
            signed_at=datetime.now(timezone.utc),
        )
        return signed


def verify_receipt(receipt: Receipt, key_registry: Mapping[str, str]) -> Tuple[bool, str]:
    if receipt.integrity is None:
        return False, "receipt has no integrity envelope"

    key_id = receipt.integrity.signer_public_key_id
    public_key_b64 = key_registry.get(key_id)
    if not public_key_b64:
        return False, f"unknown signer key: {key_id}"

    canonical = canonical_receipt_bytes(receipt)
    computed_hash = sha256_hex(canonical)
    if computed_hash != receipt.integrity.content_hash_sha256:
        return False, "canonical hash mismatch"

    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(base64.b64decode(receipt.integrity.signature_ed25519), canonical)
    except (InvalidSignature, ValueError, TypeError):
        return False, "Ed25519 signature verification failed"

    return True, "signature and canonical hash valid"
