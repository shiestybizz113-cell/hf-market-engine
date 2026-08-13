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


def _public_snapshot(doc: dict) -> dict:
    """Proof metadata only — never expose the raw vendor/provider payload."""
    return {
        "id": doc.get("snapshot_id") or doc.get("_id"),
        "snapshot_id": doc.get("snapshot_id") or doc.get("_id"),
        "domain": doc.get("domain"),
        "provider": doc.get("provider"),
        "source_reference": doc.get("source_reference"),
        "observed_at": doc.get("observed_at"),
        "ingested_at": doc.get("ingested_at"),
        "sha256": doc.get("sha256"),
        "raw_bytes": doc.get("raw_bytes"),
        "payload_truncated": doc.get("payload_truncated", False),
    }


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
    """Return a traversable receipt -> lane -> fact -> source -> snapshot graph."""
    db = get_db()
    base = await E.build_proof_graph(receipt_id, current_user["_id"], db)
    if not base:
        raise HTTPException(status_code=404, detail="Capital/mining receipt not found")

    facts = [_public_fact(f) for f in base.get("facts", [])]
    lanes_evidence = base.get("lanes_evidence", {})

    snapshots = []
    snapshot_by_id = {}
    for fact in facts:
        raw_ref = fact.get("raw_snapshot_ref")
        if not raw_ref or not raw_ref.startswith("snapshot:"):
            continue
        snapshot_id = raw_ref.split(":", 1)[1]
        if snapshot_id in snapshot_by_id:
            continue
        snap = await db.provider_snapshots.find_one({"_id": snapshot_id})
        if snap:
            public_snap = _public_snapshot(snap)
            snapshot_by_id[snapshot_id] = public_snap
            snapshots.append(public_snap)

    nodes = [{
        "kind": "receipt",
        "id": f"receipt:{receipt_id}",
        "receipt_id": receipt_id,
        "analysis_type": base.get("receipt", {}).get("analysis_type"),
    }]
    edges = []

    fact_by_id = {f["evidence_id"]: f for f in facts}
    fact_ids_in_lanes = set()

    for lane_key, lane in lanes_evidence.items():
        lane_node = f"lane:{lane_key}"
        nodes.append({
            "kind": "lane",
            "id": lane_node,
            "lane_key": lane_key,
            "label": lane.get("label", lane_key),
            "quality_label": lane.get("quality_label"),
            "quality_score": lane.get("quality_score"),
        })
        edges.append({"from": f"receipt:{receipt_id}", "to": lane_node, "relation": "contains_lane"})
        for fact_id in lane.get("facts_used", []):
            if fact_id in fact_by_id:
                fact_ids_in_lanes.add(fact_id)
                edges.append({"from": lane_node, "to": f"fact:{fact_id}", "relation": "consumed_fact"})

    source_nodes = set()
    snapshot_nodes = set()
    for fact in facts:
        fact_id = fact["evidence_id"]
        nodes.append({
            "kind": "fact",
            "id": f"fact:{fact_id}",
            "evidence_id": fact_id,
            "domain": fact.get("domain"),
            "metric": fact.get("metric"),
            "subject_id": fact.get("subject_id"),
            "value": fact.get("value"),
            "unit": fact.get("unit"),
            "state": fact.get("state"),
            "fresh": fact.get("fresh"),
            "provider": fact.get("provider"),
        })
        if fact_id not in fact_ids_in_lanes:
            edges.append({
                "from": f"receipt:{receipt_id}",
                "to": f"fact:{fact_id}",
                "relation": "receipt_context_fact",
            })

        provider = fact.get("provider") or "unknown"
        source_reference = fact.get("source_reference") or "unspecified"
        source_id = f"source:{provider}:{source_reference}"
        if source_id not in source_nodes:
            source_nodes.add(source_id)
            nodes.append({
                "kind": "source",
                "id": source_id,
                "provider": provider,
                "source_type": fact.get("source_type"),
                "source_reference": fact.get("source_reference"),
            })
        edges.append({"from": f"fact:{fact_id}", "to": source_id, "relation": "sourced_from"})

        raw_ref = fact.get("raw_snapshot_ref")
        if raw_ref and raw_ref.startswith("snapshot:"):
            snapshot_id = raw_ref.split(":", 1)[1]
            if snapshot_id in snapshot_by_id:
                snapshot_node = f"snapshot:{snapshot_id}"
                if snapshot_node not in snapshot_nodes:
                    snapshot_nodes.add(snapshot_node)
                    snap = snapshot_by_id[snapshot_id]
                    nodes.append({
                        "kind": "snapshot",
                        "id": snapshot_node,
                        "snapshot_id": snapshot_id,
                        "provider": snap.get("provider"),
                        "sha256": snap.get("sha256"),
                        "observed_at": snap.get("observed_at"),
                        "raw_bytes": snap.get("raw_bytes"),
                        "payload_truncated": snap.get("payload_truncated"),
                    })
                edges.append({"from": source_id, "to": snapshot_node, "relation": "captured_in"})

    return {
        "receipt": base.get("receipt"),
        "facts": facts,
        "lanes_evidence": lanes_evidence,
        "snapshots": snapshots,
        "graph": {"nodes": nodes, "edges": edges},
        "proof_contract": {
            "path": "receipt -> lane -> immutable evidence fact -> source/provider -> snapshot hash",
            "immutable_facts": True,
            "losing_sources_preserved": True,
            "raw_provider_payload_public": False,
            "user_scope": "global facts + requesting user's facts only",
        },
    }
