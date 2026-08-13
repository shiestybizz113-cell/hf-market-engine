"""
Evidence receipts API — user-scoped audit trail of every AI analysis.

Every receipt records the input snapshot, model, provider, estimated cost,
fallback/simulation flags and timestamp, so a user can answer "why did it say
this?" and reproduce the exact state that produced the output.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_db
from app.api.auth import get_current_user

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/receipts")
async def list_receipts(
    limit: int = 20,
    job: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    db = get_db()
    query = {"user_id": current_user["_id"]}
    if job:
        query["job"] = job
    cursor = (
        db.analysis_receipts.find(query)
        .sort("generated_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        doc["id"] = doc.pop("_id")
        doc.pop("system_prompt", None)
        out.append(doc)
    return {"count": len(out), "receipts": out}


@router.get("/receipts/{receipt_id}")
async def get_receipt(receipt_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    doc = await db.analysis_receipts.find_one(
        {"_id": receipt_id, "user_id": current_user["_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Receipt not found")
    doc["id"] = doc.pop("_id")
    return doc
