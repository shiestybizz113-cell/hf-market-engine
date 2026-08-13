"""Evidence APIs — AI receipts plus Capital V2 immutable fact/proof graph."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.core import evidence as E
from app.core.database import get_db

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _public_fact(doc: dict) -> dict:
    out = dict(doc)
    out.pop("_id", None)
    out["fresh"] = not E.is_stale(out)
    out["age_seconds"] = round(E.age_seconds(out), 1)
    return out


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
    cursor = db.analysis_receipts.find(query).sort("generated_at", -1).limit(limit)
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
    doc.pop("system_prompt", None)
    return doc


@router.get("/facts")
async def list_facts(
    domain: Optional[str] = Query(default=None),
    metric: Optional[str] = Query(default=None),
    subject_id: Optional[str] = Query(default=None),
    include_stale: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    current_user=Depends(get_current_user),
):
    db = get_db()
    query: dict = {"user_id": {"$in": [None, current_user["_id"]]}}
    if domain:
        query["domain"] = domain
    if metric:
        query["metric"] = metric
    if subject_id:
        query["subject_id"] = subject_id

    cursor = db.evidence_facts.find(query).sort("observed_at", -1).limit(limit)
    facts = []
    async for doc in cursor:
        public = _public_fact(doc)
        if include_stale or public["fresh"]:
            facts.append(public)
    return {"count": len(facts), "facts": facts}


@router.get("/facts/{evidence_id}")
async def get_fact(evidence_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    doc = await db.evidence_facts.find_one({
        "evidence_id": evidence_id,
        "user_id": {"$in": [None, current_user["_id"]]},
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Evidence fact not found")
    return _public_fact(doc)


@router.get("/graph/{receipt_id}")
async def proof_graph(receipt_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    graph = await E.build_proof_graph(receipt_id, current_user["_id"], db)
    if not graph:
        raise HTTPException(status_code=404, detail="Capital/mining receipt not found")

    snapshots = []
    seen = set()
    for fact in graph.get("facts", []):
        raw_ref = fact.get("raw_snapshot_ref")
        if not raw_ref or not raw_ref.startswith("snapshot:"):
            continue
        snapshot_id = raw_ref.split(":", 1)[1]
        if snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        snap = await db.provider_snapshots.find_one({"_id": snapshot_id})
        if snap:
            snap["id"] = snap.pop("_id")
            snapshots.append(snap)

    graph["snapshots"] = snapshots
    graph["proof_contract"] = {
        "path": "receipt -> lane -> evidence fact -> provider/source -> raw snapshot",
        "immutable_facts": True,
        "losing_sources_preserved": True,
    }
    return graph
