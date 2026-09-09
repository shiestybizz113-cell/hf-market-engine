"""
Archisynapse v1.1 — ReceiptGraph registry.

The ReceiptGraph is the append-only ledger of signed analysis receipts.
It is the enforcement point for the "No Receipt = No Analysis" doctrine.

Write contract:
  persist_receipt() — signs and writes to MongoDB.
  Returns (receipt_id, persisted: bool).
  If the DB write fails, returns persisted=False.
  Caller is responsible for flagging receipt_persisted: False.

Read contract:
  get_receipt() — returns verified SignedReceipt or None.
  list_receipts() — user-scoped, paginated, reverse-chronological.

Verification:
  verify_receipt() — offline signature check. No DB required.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.core.archisynapse.crypto import (
    canonical_json,
    sha256_hex,
    sign,
    verify,
)
from app.core.archisynapse.schema import ReceiptPayload, SignedReceipt

log = logging.getLogger("archisynapse.registry")

COLLECTION = "analysis_receipts"


# ── Build + sign ──────────────────────────────────────────────────────────────

def build_receipt(
    *,
    job: str,
    system_prompt: str,
    user_prompt: str,
    output: str,
    model: str,
    provider_name: str,
    fallback_used: bool,
    simulation: bool = False,
    user_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> SignedReceipt:
    """
    Build and cryptographically sign a receipt.
    Does not touch the database — call persist_receipt() to write.
    """
    in_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
    out_tokens = max(1, len(output) // 4)

    from app.core.archisynapse._cost import estimate_cost
    cost = estimate_cost(model, in_tokens, out_tokens)

    payload = ReceiptPayload(
        receipt_id=str(uuid.uuid4()),
        job=job,
        user_id=user_id,
        model=model,
        provider=provider_name,
        fallback_used=fallback_used,
        simulation=simulation,
        tokens_estimate={"input": in_tokens, "output": out_tokens},
        estimated_cost_usd=round(cost, 6),
        generated_at=time.time(),
        input_hash=sha256_hex(system_prompt + "\n" + user_prompt),
        output_hash=sha256_hex(output),
        extra=extra,
    )

    payload_dict = payload.model_dump()
    payload_str = canonical_json(payload_dict)
    sig_hex, pub_hex = sign(payload_str)

    return SignedReceipt(
        payload=payload,
        payload_json=payload_str,
        signature=sig_hex,
        public_key=pub_hex,
    )


# ── Persist ───────────────────────────────────────────────────────────────────

async def persist_receipt(
    receipt: SignedReceipt,
    db,
) -> tuple[str, bool]:
    """
    Write the signed receipt to MongoDB.
    Returns (receipt_id, persisted: bool).
    Never raises — DB failures return persisted=False.
    """
    receipt_id = receipt.payload.receipt_id
    try:
        doc = receipt.to_db_doc()
        await db[COLLECTION].insert_one(doc)
        log.debug("Receipt persisted: %s (job=%s)", receipt_id, receipt.payload.job)
        return receipt_id, True
    except Exception as exc:
        log.error(
            "Receipt NOT persisted: %s (job=%s) — %s",
            receipt_id, receipt.payload.job, exc
        )
        return receipt_id, False


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_receipt(
    receipt_id: str,
    user_id: str,
    db,
) -> SignedReceipt | None:
    """Fetch and verify a single receipt. Returns None if missing or invalid."""
    doc = await db[COLLECTION].find_one(
        {"_id": receipt_id, "user_id": user_id}
    )
    if not doc:
        return None
    try:
        receipt = SignedReceipt.from_db_doc(doc)
    except Exception as e:
        log.warning("Malformed receipt %s: %s", receipt_id, e)
        return None
    return receipt


async def list_receipts(
    user_id: str,
    db,
    *,
    job: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> list[dict[str, Any]]:
    """
    List user receipts, reverse-chronological, with signature verified inline.
    Corrupted/tampered receipts are included but flagged signature_valid=False.
    """
    query: dict[str, Any] = {"user_id": user_id}
    if job:
        query["job"] = job

    cursor = (
        db[COLLECTION]
        .find(query)
        .sort("generated_at", -1)
        .skip(skip)
        .limit(limit)
    )

    out = []
    async for doc in cursor:
        try:
            receipt = SignedReceipt.from_db_doc(doc)
            sig_valid = verify_receipt(receipt)
            row = receipt.payload.model_dump()
            row["id"] = row.pop("receipt_id")
            row["signature_valid"] = sig_valid
            row["receipt_persisted"] = receipt.receipt_persisted
            row["public_key"] = receipt.public_key
        except Exception as e:
            # Malformed doc — surface it but mark invalid
            row = {"id": str(doc.get("_id")), "error": str(e), "signature_valid": False}
        out.append(row)
    return out


# ── Verify ────────────────────────────────────────────────────────────────────

def verify_receipt(receipt: SignedReceipt) -> bool:
    """
    Offline Ed25519 signature verification.
    No DB required. Returns True if receipt is unmodified since signing.
    """
    return verify(receipt.payload_json, receipt.signature, receipt.public_key)
