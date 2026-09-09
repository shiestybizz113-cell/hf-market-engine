"""
Archisynapse v1.1 — Receipt schema.

Pydantic models for the signed analysis receipt envelope.
The envelope separates signed payload from trust overlay so
authenticity (signature) is never conflated with current trust status.

Schema is forward-compatible with Archisynapse v2 (payment microservices).
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class ReceiptPayload(BaseModel):
    """
    The canonical, signable receipt body.
    All fields here are frozen at signing time — no post-hoc mutation.
    """
    receipt_id: str = Field(..., description="UUID v4 — globally unique")
    job: str = Field(..., description="AI job type e.g. asset_thesis, journal_review")
    user_id: str | None = Field(None, description="Authenticated user; None for system jobs")
    model: str
    provider: str
    fallback_used: bool
    simulation: bool = False
    tokens_estimate: dict[str, int] = Field(default_factory=dict)
    estimated_cost_usd: float
    generated_at: float = Field(default_factory=time.time)
    input_hash: str = Field(..., description="SHA-256 of canonical(system_prompt + user_prompt)")
    output_hash: str = Field(..., description="SHA-256 of output text")
    extra: dict[str, Any] | None = None


class SignedReceipt(BaseModel):
    """
    The full persisted receipt envelope.
    payload_json: canonical JSON of ReceiptPayload (what was signed)
    signature:    hex-encoded Ed25519 signature over payload_json bytes
    public_key:   hex-encoded Ed25519 public key (for offline verification)
    trust:        mutable trust overlay — does NOT affect signature validity
    """
    payload: ReceiptPayload
    payload_json: str = Field(..., description="Canonical JSON — exactly what was signed")
    signature: str = Field(..., description="Hex Ed25519 signature")
    public_key: str = Field(..., description="Hex Ed25519 public key")
    receipt_persisted: bool = True
    trust: dict[str, Any] = Field(default_factory=dict)

    def to_db_doc(self) -> dict[str, Any]:
        """Flatten to MongoDB document. _id = receipt_id."""
        doc = self.payload.model_dump()
        doc["_id"] = doc.pop("receipt_id")
        doc["payload_json"] = self.payload_json
        doc["signature"] = self.signature
        doc["public_key"] = self.public_key
        doc["receipt_persisted"] = self.receipt_persisted
        doc["trust"] = self.trust
        return doc

    @classmethod
    def from_db_doc(cls, doc: dict[str, Any]) -> SignedReceipt:
        """Reconstruct from MongoDB document."""
        d = dict(doc)
        receipt_id = d.pop("_id")
        payload_json = d.pop("payload_json")
        signature = d.pop("signature")
        public_key = d.pop("public_key")
        receipt_persisted = d.pop("receipt_persisted", True)
        trust = d.pop("trust", {})
        d["receipt_id"] = receipt_id
        payload = ReceiptPayload(**d)
        return cls(
            payload=payload,
            payload_json=payload_json,
            signature=signature,
            public_key=public_key,
            receipt_persisted=receipt_persisted,
            trust=trust,
        )
