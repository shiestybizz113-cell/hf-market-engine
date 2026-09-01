"""
Assets / Fleet API — customer-owned hardware and capital registry.

Operators register what they already own so the capital engine can:
  1. Account for existing power consumption before recommending new purchases.
  2. Value owned mining / GPU rigs as a baseline alongside new-purchase lanes.
  3. Include owned treasury (BTC) and storage in the total picture.
  4. Show the proof drawer exactly which fleet assets back each capital receipt.

Assets are NEVER hard-deleted. They are retired (status -> retired) which
creates a new fleet fact pointing at 0 value and superseding the active one.
We evolve, we don't delete.
"""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import assets as A
from app.api.auth import get_current_user
from app.core.database import get_db

router = APIRouter(prefix="/assets", tags=["assets"])


class AssetCreateRequest(BaseModel):
    asset_type: str = Field(description="asic | gpu | power | storage | treasury")
    name: Optional[str] = None
    subject: Optional[str] = None
    units: int = Field(ge=1, default=1)
    value_usd: float = Field(ge=0, default=0.0)
    hashrate_ths_per_unit: Optional[float] = Field(default=None, ge=0)
    power_kw_per_unit: Optional[float] = Field(default=None, ge=0)
    power_mw: Optional[float] = Field(default=None, ge=0)
    storage_mwh: Optional[float] = Field(default=None, ge=0)
    energy_acquisition_usd_kwh: Optional[float] = Field(default=None, ge=0)
    btc_qty: Optional[float] = Field(default=None, ge=0)
    acquisition_date: Optional[str] = None
    region: Optional[str] = None
    notes: Optional[str] = None


class AssetUpdateRequest(BaseModel):
    name: Optional[str] = None
    value_usd: Optional[float] = Field(default=None, ge=0)
    power_mw: Optional[float] = Field(default=None, ge=0)
    storage_mwh: Optional[float] = Field(default=None, ge=0)
    btc_qty: Optional[float] = Field(default=None, ge=0)
    hashrate_ths_per_unit: Optional[float] = Field(default=None, ge=0)
    power_kw_per_unit: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None


class AssetImportRequest(BaseModel):
    assets: list


@router.post("")
async def create_asset(
    body: AssetCreateRequest,
    current_user=Depends(get_current_user),
):
    """Create an owned asset (fleet fact)."""
    doc = await A.create_asset(body.model_dump(), current_user["_id"], _db=get_db())
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.get("")
async def list_assets(
    current_user=Depends(get_current_user),
):
    """List all assets (full history; retired assets included)."""
    docs = await A.list_assets(current_user["_id"], _db=get_db())
    for d in docs:
        d.pop("user_id", None)
    return {"count": len(docs), "assets": docs}


@router.get("/fleet")
async def fleet_summary(current_user=Depends(get_current_user)):
    """Aggregated fleet summary used by the capital engine."""
    summary = await A.fleet_summary(current_user["_id"], _db=get_db())
    return summary


@router.patch("/{asset_id}")
async def update_asset(
    asset_id: str,
    body: AssetUpdateRequest,
    current_user=Depends(get_current_user),
):
    """Update an active asset's parameters (value, power, etc.)."""
    db = get_db()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        return {"ok": True, "message": "Nothing to update"}
    await db.assets.update_one(
        {"_id": asset_id, "user_id": current_user["_id"]},
        {"$set": update},
    )
    doc = await db.assets.find_one({"_id": asset_id, "user_id": current_user["_id"]})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.post("/{asset_id}/retire")
async def retire_asset(
    asset_id: str,
    current_user=Depends(get_current_user),
):
    """Retire an asset: supersede its fleet fact, keep history."""
    doc = await A.retire_asset(asset_id, current_user["_id"], _db=get_db())
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.post("/{asset_id}/reactivate")
async def reactivate_asset(
    asset_id: str,
    current_user=Depends(get_current_user),
):
    doc = await A.reactivate_asset(asset_id, current_user["_id"], _db=get_db())
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.post("/import")
async def import_assets(
    body: AssetImportRequest,
    current_user=Depends(get_current_user),
):
    """Bulk import assets."""
    result = await A.import_assets(body.model_dump(), current_user["_id"], _db=get_db())
    for d in result.get("created", []):
        d.pop("_id", None)
        d.pop("user_id", None)
    return result
