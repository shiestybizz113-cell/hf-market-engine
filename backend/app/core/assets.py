"""Customer asset / fleet registry for Capital Command Center V2.

Assets are mutable current-state records; their evidence is not. Every create,
update, retire, or reactivation emits (or reuses) an immutable fleet fact so a
Capital receipt can reconstruct the operator state it used.

There is intentionally no hard-delete path. Assets retire and history remains.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.database import get_db
from app.core.evidence_broker import capture_observation
from app.core import evidence as E

ASSET_TYPES = ("asic", "gpu", "power", "storage", "treasury")
ACTIVE = "active"
RETIRED = "retired"
STATUSES = (ACTIVE, RETIRED)

ASSET_METRIC = {
    "asic": "asset_asic",
    "gpu": "asset_gpu",
    "power": "asset_power",
    "storage": "asset_storage",
    "treasury": "asset_treasury",
}

_PATCHABLE = {
    "name", "subject", "units", "value_usd", "currency", "source", "status",
    "hashrate_ths_per_unit", "power_kw_per_unit", "power_mw", "storage_mwh",
    "energy_acquisition_usd_kwh", "btc_qty", "acquisition_date", "region",
    "notes",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_number(value, default=0.0) -> float:
    if value is None or value == "":
        return float(default)
    return float(value)


def normalize_asset(payload: Dict, *, existing: Optional[Dict] = None) -> Dict:
    """Validate + normalize an asset payload, optionally merging with a record."""
    base = dict(existing or {})
    merged = {**base, **{k: v for k, v in payload.items() if k in _PATCHABLE or k == "asset_type"}}

    asset_type = merged.get("asset_type")
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type must be one of {', '.join(ASSET_TYPES)}")

    status = merged.get("status", ACTIVE)
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")

    units = int(merged.get("units", 1))
    if units < 1:
        raise ValueError("units must be >= 1")

    doc: Dict = {
        "asset_type": asset_type,
        "name": merged.get("name") or merged.get("subject") or asset_type,
        "subject": merged.get("subject") or merged.get("name") or asset_type,
        "units": units,
        "value_usd": _clean_number(merged.get("value_usd"), 0.0),
        "currency": merged.get("currency", "USD"),
        "source": merged.get("source", "user_input"),
        "status": status,
    }

    numeric_optional = (
        "hashrate_ths_per_unit", "power_kw_per_unit", "power_mw",
        "storage_mwh", "energy_acquisition_usd_kwh", "btc_qty",
    )
    for key in numeric_optional:
        if merged.get(key) is not None:
            doc[key] = _clean_number(merged[key])

    for key in ("acquisition_date", "region", "notes"):
        if merged.get(key) is not None:
            doc[key] = merged[key]

    if asset_type == "asic":
        if doc.get("hashrate_ths_per_unit", 0) < 0 or doc.get("power_kw_per_unit", 0) < 0:
            raise ValueError("ASIC hashrate/power must be >= 0")
    if asset_type == "gpu" and doc.get("power_kw_per_unit", 0) < 0:
        raise ValueError("GPU power_kw_per_unit must be >= 0")
    if asset_type == "power" and doc.get("power_mw", 0) < 0:
        raise ValueError("power_mw must be >= 0")
    if asset_type == "storage" and doc.get("storage_mwh", 0) < 0:
        raise ValueError("storage_mwh must be >= 0")

    return doc


def _public(doc: Dict) -> Dict:
    out = dict(doc)
    raw_id = out.pop("_id", None)
    out["asset_id"] = out.get("asset_id") or raw_id
    return out


def _fact_value_and_unit(doc: Dict) -> tuple[float, str]:
    asset_type = doc["asset_type"]
    if doc.get("status") == RETIRED:
        return 0.0, "retired"
    if asset_type in ("asic", "gpu"):
        return float(doc.get("units", 0)), "units"
    if asset_type == "power":
        return float(doc.get("power_mw", 0.0)), "mw"
    if asset_type == "storage":
        return float(doc.get("storage_mwh", 0.0)), "mwh"
    btc_qty = float(doc.get("btc_qty", 0.0) or 0.0)
    if btc_qty:
        return btc_qty, "btc"
    return float(doc.get("value_usd", 0.0)), "usd"


async def _fleet_fact(doc: Dict, _db=None) -> str:
    value, unit = _fact_value_and_unit(doc)
    extra = {
        "asset_id": doc["asset_id"],
        "asset_type": doc["asset_type"],
        "units": doc.get("units", 1),
        "name": doc.get("name"),
        "subject": doc.get("subject"),
        "status": doc.get("status", ACTIVE),
        "value_usd": float(doc.get("value_usd", 0.0) or 0.0),
    }
    for key in (
        "hashrate_ths_per_unit", "power_kw_per_unit", "power_mw",
        "storage_mwh", "btc_qty", "energy_acquisition_usd_kwh",
        "region", "acquisition_date",
    ):
        if doc.get(key) is not None:
            extra[key] = doc[key]

    return await capture_observation(
        domain="fleet",
        metric=ASSET_METRIC[doc["asset_type"]],
        subject_id=doc["asset_id"],
        value=value,
        unit=unit,
        state=E.USER_ASSUMPTION,
        provider="user_input",
        source_type="user_input",
        user_id=doc.get("user_id"),
        raw_snapshot_ref=f"asset:{doc['asset_id']}",
        methodology="Operator asset registry snapshot",
        extra=extra,
        _db=_db,
    )


async def create_asset(payload: Dict, user_id: str, _db=None) -> Dict:
    db = _db or get_db()
    normalized = normalize_asset(payload)
    asset_id = str(uuid.uuid4())
    now = _now()
    doc = {
        **normalized,
        "_id": asset_id,
        "asset_id": asset_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
    }
    doc["evidence_id"] = await _fleet_fact(doc, db)
    await db.assets.insert_one(doc)
    return _public(doc)


async def import_assets(payload: Dict, user_id: str, _db=None) -> Dict:
    items = payload.get("assets", [])
    if not isinstance(items, list):
        raise ValueError("assets must be a list")
    if len(items) > 500:
        raise ValueError("asset import is limited to 500 rows per request")

    created, errors = [], []
    for index, item in enumerate(items):
        try:
            created.append(await create_asset(item, user_id, _db))
        except (ValueError, TypeError) as exc:
            errors.append({"index": index, "error": str(exc)})
    return {"created": created, "errors": errors, "created_count": len(created)}


async def get_asset(asset_id: str, user_id: str, _db=None) -> Optional[Dict]:
    db = _db or get_db()
    doc = await db.assets.find_one({"_id": asset_id, "user_id": user_id})
    return _public(doc) if doc else None


async def update_asset(asset_id: str, payload: Dict, user_id: str, _db=None) -> Optional[Dict]:
    db = _db or get_db()
    current = await db.assets.find_one({"_id": asset_id, "user_id": user_id})
    if not current:
        return None

    if payload.get("asset_type") and payload["asset_type"] != current.get("asset_type"):
        raise ValueError("asset_type cannot be changed; retire and create a new asset instead")

    normalized = normalize_asset(payload, existing=current)
    next_doc = {
        **current,
        **normalized,
        "asset_id": asset_id,
        "user_id": user_id,
        "updated_at": _now(),
    }
    next_doc["evidence_id"] = await _fleet_fact(next_doc, db)

    set_fields = {k: v for k, v in next_doc.items() if k != "_id"}
    await db.assets.update_one({"_id": asset_id, "user_id": user_id}, {"$set": set_fields})
    return _public(next_doc)


async def retire_asset(asset_id: str, user_id: str, _db=None) -> Optional[Dict]:
    return await update_asset(asset_id, {"status": RETIRED}, user_id, _db)


async def reactivate_asset(asset_id: str, user_id: str, _db=None) -> Optional[Dict]:
    return await update_asset(asset_id, {"status": ACTIVE}, user_id, _db)


async def list_assets(user_id: str, _db=None, active_only: bool = False) -> List[Dict]:
    db = _db or get_db()
    query: Dict = {"user_id": user_id}
    if active_only:
        query["status"] = ACTIVE
    cursor = db.assets.find(query).sort("created_at", -1)
    return [_public(doc) async for doc in cursor]


async def fleet_summary(user_id: str, _db=None) -> Dict:
    """Aggregate active assets and refresh their evidence snapshot if needed."""
    db = _db or get_db()
    assets = await list_assets(user_id, db, active_only=True)
    summary: Dict = {
        "asics": {"units": 0, "hashrate_ths": 0.0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "gpus": {"units": 0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "power_mw": 0.0,
        "storage_mwh": 0.0,
        "treasury_btc": 0.0,
        "treasury_usd": 0.0,
        "total_value_usd": 0.0,
        "asset_count": len(assets),
        "evidence_ids": [],
    }

    for public_asset in assets:
        internal = {**public_asset, "_id": public_asset["asset_id"]}
        evidence_id = await _fleet_fact(internal, db)
        summary["evidence_ids"].append(evidence_id)
        if evidence_id != public_asset.get("evidence_id"):
            await db.assets.update_one(
                {"_id": public_asset["asset_id"], "user_id": user_id},
                {"$set": {"evidence_id": evidence_id, "updated_at": _now()}},
            )

        value_usd = float(public_asset.get("value_usd", 0.0) or 0.0)
        summary["total_value_usd"] += value_usd
        asset_type = public_asset["asset_type"]
        units = int(public_asset.get("units", 1))

        if asset_type == "asic":
            hashrate = float(public_asset.get("hashrate_ths_per_unit", 0.0) or 0.0)
            power = float(public_asset.get("power_kw_per_unit", 0.0) or 0.0)
            summary["asics"]["units"] += units
            summary["asics"]["hashrate_ths"] += hashrate * units
            summary["asics"]["power_kw"] += power * units
            summary["asics"]["value_usd"] += value_usd
            summary["asics"]["models"].append({
                "asset_id": public_asset["asset_id"],
                "model": public_asset.get("subject"),
                "units": units,
                "hashrate_ths": hashrate * units,
                "power_kw": power * units,
            })
        elif asset_type == "gpu":
            power = float(public_asset.get("power_kw_per_unit", 0.0) or 0.0)
            summary["gpus"]["units"] += units
            summary["gpus"]["power_kw"] += power * units
            summary["gpus"]["value_usd"] += value_usd
            summary["gpus"]["models"].append({
                "asset_id": public_asset["asset_id"],
                "model": public_asset.get("subject"),
                "units": units,
                "power_kw": power * units,
            })
        elif asset_type == "power":
            summary["power_mw"] += float(public_asset.get("power_mw", 0.0) or 0.0)
        elif asset_type == "storage":
            summary["storage_mwh"] += float(public_asset.get("storage_mwh", 0.0) or 0.0)
        elif asset_type == "treasury":
            summary["treasury_btc"] += float(public_asset.get("btc_qty", 0.0) or 0.0)
            summary["treasury_usd"] += value_usd

    summary["evidence_ids"] = list(dict.fromkeys(summary["evidence_ids"]))
    return summary
