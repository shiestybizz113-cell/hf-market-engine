"""
Evidence receipts + facts API — Archisynapse v1.1 + V2 evidence fabric.

Every AI analysis call produces a cryptographically signed receipt.
This API lets authenticated users inspect, verify, and audit their
receipt history.

V2 adds:
  GET  /evidence/facts              — list immutable evidence facts
  GET  /evidence/facts/{fact_id}    — single fact with full trace
  GET  /evidence/graph/{receipt_id} — receipt -> facts -> sources proof graph
  POST /evidence/seed               — seed reference facts from catalogs

Endpoints:
  GET  /evidence/receipts          — list receipts (paginated, verified inline)
  GET  /evidence/receipts/{id}     — single receipt with full verification
  GET  /evidence/public-key        — deployment's Ed25519 public key (offline verify)
  POST /evidence/verify            — offline verify a receipt payload
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.core import evidence as E
from app.core.archisynapse import (
    get_public_key_hex,
    get_receipt,
    list_receipts,
    verify_receipt,
)
from app.core.archisynapse.crypto import verify
from app.core.database import get_db
from app.core.evidence_broker import capture_observation
from app.core.gpu import GPU_CATALOG
from app.core.mining import ASIC_CATALOG

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/receipts")
async def list_user_receipts(
    limit: int = 20,
    skip: int = 0,
    job: str | None = None,
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


# --------------------------------------------------------------------------- #
# V2 Evidence Fabric
# --------------------------------------------------------------------------- #

@router.get("/facts")
async def list_facts(
    domain: str | None = None,
    metric: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """List immutable evidence facts. Scoped to the caller + system facts."""
    db = get_db()
    if domain and metric:
        facts = await E.facts_for(
            domain=domain, metric=metric, subject_id=subject_id,
            user_id=current_user["_id"], limit=limit, _db=db,
        )
    else:
        # Broad query: user_id scope, latest facts
        scope = [None, current_user["_id"]]
        query: dict = {}
        if domain:
            query["domain"] = domain
        query["user_id"] = {"$in": scope}
        cursor = db.evidence_facts.find(query).sort("observed_at", -1).limit(limit)
        facts = []
        async for doc in cursor:
            doc.pop("_id", None)
            facts.append(doc)
    for f in facts:
        f["age_seconds"] = round(E.age_seconds(f), 1)
        f["fresh"] = not E.is_stale(f)
    return {"count": len(facts), "facts": facts}


@router.get("/facts/{fact_id}")
async def get_fact(
    fact_id: str,
    current_user=Depends(get_current_user),
):
    """Single evidence fact with full provenance and freshness."""
    db = get_db()
    fact = await E.get_fact(fact_id, db)
    if not fact:
        raise HTTPException(status_code=404, detail="Evidence fact not found")
    fact["age_seconds"] = round(E.age_seconds(fact), 1)
    fact["fresh"] = not E.is_stale(fact)
    return fact


@router.get("/graph/{receipt_id}")
async def proof_graph(
    receipt_id: str,
    current_user=Depends(get_current_user),
):
    """Proof graph: receipt -> evidence facts -> sources.

    Reconstructs every calculation the receipt consumed so the proof drawer
    can show exactly which facts, providers and observations backed each number.
    """
    graph = await E.build_proof_graph(receipt_id, current_user["_id"], _db=get_db())
    if not graph:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return graph


@router.post("/seed")
async def seed_reference_facts(
    current_user=Depends(get_current_user),
):
    """Seed reference facts from ASIC + GPU catalogs.

    Idempotent: capture_observation dedupes against the latest fresh fact
    with the same (domain, metric, subject, provider). Safe to call repeatedly.
    """
    db = get_db()
    seeded = []

    # ASIC reference facts: price + hashrate + power per model.
    for key, cat in ASIC_CATALOG.items():
        for metric, value, unit in [
            ("asic_price", float(cat["price_usd"]), "usd"),
            ("asic_hashrate", float(cat["hashrate_ths"]), "ths"),
            ("asic_power", float(cat["power_watts"]), "watts"),
        ]:
            eid = await capture_observation(
                domain="hardware", metric=metric, subject_id=key,
                value=value, unit=unit, state=E.USER_ASSUMPTION,
                provider="reference_catalog", source_type="reference",
                _db=db,
            )
            seeded.append({"domain": "hardware", "metric": metric, "subject": key, "fact_id": eid})

    # GPU reference facts: capex + power + cloud rental per model.
    for key, cat in GPU_CATALOG.items():
        for metric, value, unit in [
            ("gpu_capex", float(cat["capex_usd"]), "usd"),
            ("gpu_power", float(cat["power_kw"]), "kw"),
            ("compute_offer", float(cat["cloud_rental_usd_hr"]), "usd_hr"),
        ]:
            eid = await capture_observation(
                domain="gpu", metric=metric, subject_id=key,
                value=value, unit=unit, state=E.USER_ASSUMPTION,
                provider="reference_catalog", source_type="reference",
                _db=db,
            )
            seeded.append({"domain": "gpu", "metric": metric, "subject": key, "fact_id": eid})

    return {"ok": True, "seeded": len(seeded), "facts": seeded}
