"""
Customer asset / fleet registry.

Asset types:
    asic      - Bitcoin mining rigs (units, hashrate_ths_per_unit, power_kw_per_unit)
    gpu       - GPU units (power_kw_per_unit)
    power     - owned power capacity (power_mw) — site / grid / solar allocation
    storage   - energy storage (storage_mwh)
    treasury  - BTC held (btc_qty) or fiat/cash (value_usd)

Every asset is linked to an immutable fleet evidence fact so the capital
engine and the proof drawer can show where "the customer already owns this"
came from. Assets are NEVER hard-deleted: they are retired (status ->
retired), which supersedes their fleet fact. We evolve, we don't delete.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.database import get_db
from app.core.evidence_broker import capture_observation
from app.core import evidence as E

ASSET_TYPES = ("asic", "gpu", "power", "storage", "treasury")

# Which fleet metric each asset type contributes to.
ASSET_METRIC = {
    "asic": "asset_asic",
    "gpu": "asset_gpu",
    "power": "asset_power",
    "storage": "asset_storage",
    "treasury": "asset_treasury",
}

ACTIVE = "active"
RETIRED = "retired"
STATUSES = (ACTIVE, RETIRED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_asset(payload: Dict) -> Dict:
    """Validate + fill an asset document from an API payload."""
    asset_type = payload.get("asset_type")
    if asset_type not in ASSET_TYPES:
        raise ValueError(
            f"asset_type must be one of {', '.join(ASSET_TYPES)}"
        )
    status = payload.get("status", ACTIVE)
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")

    units = int(payload.get("units", 1))
    if units < 1:
        raise ValueError("units must be >= 1")

    doc: Dict = {
        "asset_type": asset_type,
        "name": payload.get("name") or payload.get("subject") or asset_type,
        "subject": payload.get("subject") or payload.get("name") or asset_type,
        "units": units,
        "value_usd": float(payload.get("value_usd", 0.0)),
        "currency": payload.get("currency", "USD"),
        "source": payload.get("source", "user_input"),
        "status": status,
        "created_at": _now(),
        "updated_at": _now(),
    }
    optional = {
        "hashrate_ths_per_unit": "hashrate_ths_per_unit",
        "power_kw_per_unit": "power_kw_per_unit",
        "power_mw": "power_mw",
        "storage_mwh": "storage_mwh",
        "energy_acquisition_usd_kwh": "energy_acquisition_usd_kwh",
        "btc_qty": "btc_qty",
        "acquisition_date": "acquisition_date",
        "region": "region",
        "notes": "notes",
    }
    for src, dst in optional.items():
        if payload.get(src) is not None:
            doc[dst] = payload[src]
    return doc


async def create_asset(payload: Dict, user_id: str, _db=None) -> Dict:
    """Create an asset AND its immutable fleet fact. Returns the asset doc."""
    db = _db or get_db()
    doc = normalize_asset(payload)
    doc["_id"] = str(uuid.uuid4())
    doc["user_id"] = user_id

    # Fleet evidence fact (persistent: expires only on change/retire).
    evidence_id = await _fleet_fact(doc)
    doc["evidence_id"] = evidence_id
    await db.assets.insert_one(doc)
    return doc


async def import_assets(payload: Dict, user_id: str, _db=None) -> Dict:
    """Bulk import assets. Returns created docs + skipped errors."""
    items = payload.get("assets", [])
    if not isinstance(items, list):
        raise ValueError("assets must be a list")
    db = _db or get_db()
    created = []
    errors = []
    for i, item in enumerate(items):
        try:
            doc = normalize_asset(item)
            doc["_id"] = str(uuid.uuid4())
            doc["user_id"] = user_id
            doc["source"] = item.get("source", "import")
            evidence_id = await _fleet_fact(doc)
            doc["evidence_id"] = evidence_id
            await db.assets.insert_one(doc)
            created.append(doc)
        except ValueError as exc:
            errors.append({"index": i, "error": str(exc)})
    return {"created": created, "errors": errors}


async def _fleet_fact(doc: Dict, _db=None) -> str:
    """Append (or reuse) the fleet fact for an asset."""
    value = float(doc.get("value_usd", 0.0))
    extra = {
        "asset_type": doc["asset_type"],
        "units": doc["units"],
        "name": doc.get("name"),
    }
    for k in ("hashrate_ths_per_unit", "power_kw_per_unit", "power_mw",
              "storage_mwh", "btc_qty", "energy_acquisition_usd_kwh"):
        if doc.get(k) is not None:
            extra[k] = doc[k]
    return await capture_observation(
        domain="fleet",
        metric=ASSET_METRIC[doc["asset_type"]],
        subject_id=doc["_id"],
        value=value,
        unit="usd",
        state=E.USER_ASSUMPTION,
        provider="user_input",
        source_type="user_input",
        user_id=doc.get("user_id"),
        raw_snapshot_ref=f"asset:{doc['_id']}",
        extra=extra,
        _db=_db,
    )


async def retire_asset(asset_id: str, user_id: str, _db=None) -> Optional[Dict]:
    """Retire an asset: supersede its fleet fact, keep history. Returns doc."""
    db = _db or get_db()
    asset = await db.assets.find_one({"_id": asset_id, "user_id": user_id})
    if not asset:
        return None
    if asset.get("status") == RETIRED:
        return asset

    new_fact_id = await capture_observation(
        domain="fleet",
        metric=ASSET_METRIC[asset["asset_type"]],
        subject_id=asset["_id"],
        value=0.0,
        unit="usd",
        state=E.USER_ASSUMPTION,
        provider="user_input",
        source_type="user_input",
        user_id=user_id,
        raw_snapshot_ref=f"asset:{asset['_id']}:retired",
        _db=_db,
    )
    await db.assets.update_one(
        {"_id": asset_id},
        {"$set": {"status": RETIRED, "updated_at": _now(), "evidence_id": new_fact_id}},
    )
    asset["status"] = RETIRED
    asset["updated_at"] = _now()
    asset["evidence_id"] = new_fact_id
    return asset


async def reactivate_asset(asset_id: str, user_id: str, _db=None) -> Optional[Dict]:
    db = _db or get_db()
    asset = await db.assets.find_one({"_id": asset_id, "user_id": user_id})
    if not asset:
        return None
    new_fact_id = await _fleet_fact(asset, _db)
    await db.assets.update_one(
        {"_id": asset_id},
        {"$set": {"status": ACTIVE, "updated_at": _now(), "evidence_id": new_fact_id}},
    )
    asset["status"] = ACTIVE
    asset["updated_at"] = _now()
    asset["evidence_id"] = new_fact_id
    return asset


async def list_assets(user_id: str, _db=None, active_only: bool = False) -> List[Dict]:
    db = _db or get_db()
    query: Dict = {"user_id": user_id}
    if active_only:
        query["status"] = ACTIVE
    cursor = db.assets.find(query).sort("created_at", -1)
    out = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return out


async def fleet_summary(user_id: str, _db=None) -> Dict:
    """Aggregate active assets into the fleet block the capital engine uses."""
    assets = await list_assets(user_id, _db, active_only=True)
    summary: Dict = {
        "asics": {"units": 0, "hashrate_ths": 0.0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "gpus": {"units": 0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "power_mw": 0.0,
        "storage_mwh": 0.0,
        "treasury_btc": 0.0,
        "treasury_usd": 0.0,
        "total_value_usd": 0.0,
        "asset_count": len(assets),
    }
    for a in assets:
        summary["total_value_usd"] += float(a.get("value_usd", 0.0))
        at = a["asset_type"]
        if at == "asic":
            h = float(a.get("hashrate_ths_per_unit", 0.0))
            p = float(a.get("power_kw_per_unit", 0.0))
            summary["asics"]["units"] += a["units"]
            summary["asics"]["hashrate_ths"] += h * a["units"]
            summary["asics"]["power_kw"] += p * a["units"]
            summary["asics"]["value_usd"] += float(a.get("value_usd", 0.0))
            summary["asics"]["models"].append(
                {"model": a.get("subject"), "units": a["units"],
                 "hashrate_ths": h * a["units"], "power_kw": p * a["units"]}
            )
        elif at == "gpu":
            p = float(a.get("power_kw_per_unit", 0.0))
            summary["gpus"]["units"] += a["units"]
            summary["gpus"]["power_kw"] += p * a["units"]
            summary["gpus"]["value_usd"] += float(a.get("value_usd", 0.0))
            summary["gpus"]["models"].append(
                {"model": a.get("subject"), "units": a["units"], "power_kw": p * a["units"]}
            )
        elif at == "power":
            summary["power_mw"] += float(a.get("power_mw", 0.0))
        elif at == "storage":
            summary["storage_mwh"] += float(a.get("storage_mwh", 0.0))
        elif at == "treasury":
            summary["treasury_btc"] += float(a.get("btc_qty", 0.0))
            summary["treasury_usd"] += float(a.get("value_usd", 0.0))
    return summary
