"""
Evidence receipts API — Archisynapse v1.1

Every AI analysis call produces a cryptographically signed receipt.
This API lets authenticated users inspect, verify, and audit their
receipt history.

Endpoints:
  GET  /evidence/receipts          — list receipts (paginated, verified inline)
  GET  /evidence/receipts/{id}     — single receipt with full verification
  GET  /evidence/public-key        — deployment's Ed25519 public key (offline verify)
  POST /evidence/verify            — offline verify a receipt payload
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.database import get_db
from app.api.auth import get_current_user
from app.core.archisynapse import (
    get_receipt,
    list_receipts,
    verify_receipt,
    get_public_key_hex,
    SignedReceipt,
)
from app.core.archisynapse.crypto import verify

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/receipts")
async def list_user_receipts(
    limit: int = 20,
    skip: int = 0,
    job: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """
    List the current user's AI analysis receipts, newest first.
    Each receipt includes signature_valid — offline Ed25519 verification
    run at query time. Any False means the receipt was tampered with
    after signing.
    """
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")

    db = get_db()
    receipts = await list_receipts(
        user_id=current_user["_id"],
        db=db,
        job=job,
        limit=limit,
        skip=skip,
    )
    return {"count": len(receipts), "receipts": receipts}


@router.get("/receipts/{receipt_id}")
async def get_single_receipt(
    receipt_id: str,
    current_user=Depends(get_current_user),
):
    """
    Fetch a single receipt with full signature verification.
    Returns 404 if not found or belongs to another user.
    Returns 200 with signature_valid=False if the receipt was tampered.
    """
    db = get_db()
    receipt = await get_receipt(
        receipt_id=receipt_id,
        user_id=current_user["_id"],
        db=db,
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    sig_valid = verify_receipt(receipt)
    row = receipt.payload.model_dump()
    row["id"] = row.pop("receipt_id")
    row["signature_valid"] = sig_valid
    row["signature"] = receipt.signature
    row["public_key"] = receipt.public_key
    row["payload_json"] = receipt.payload_json
    row["receipt_persisted"] = receipt.receipt_persisted

    return row


@router.get("/public-key")
async def deployment_public_key():
    """
    Returns the Ed25519 public key for this deployment.
    Use this to verify any receipt offline without contacting the API:

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        pub.verify(bytes.fromhex(signature), payload_json.encode())
    """
    return {
        "public_key": get_public_key_hex(),
        "algorithm": "Ed25519",
        "usage": "Verify receipt.payload_json with receipt.signature",
    }


class VerifyRequest(BaseModel):
    payload_json: str
    signature: str
    public_key: str


@router.post("/verify")
async def verify_receipt_payload(body: VerifyRequest):
    """
    Offline verify any receipt payload without authentication.
    Useful for third-party auditors who hold a receipt export.
    """
    valid = verify(body.payload_json, body.signature, body.public_key)
    return {
        "signature_valid": valid,
        "message": "Receipt is authentic and unmodified." if valid
                   else "Signature verification FAILED — receipt may have been tampered with.",
    }
