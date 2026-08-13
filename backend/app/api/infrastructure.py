"""Capital V2 infrastructure data + operator asset APIs."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.core import assets
from app.core.infrastructure_data import (
    list_compute_offers,
    list_energy_prices,
    list_hardware_offers,
)
from app.core.plans import require_feature
from app.core.redaction import scrub_public_sources

router = APIRouter(tags=["capital-infrastructure"])


@router.get("/hardware/offers")
async def hardware_offers(current_user=Depends(get_current_user)):
    return scrub_public_sources(await list_hardware_offers(current_user["_id"]))


@router.get("/compute/offers")
async def compute_offers(
    model: Optional[str] = Query(default=None),
    region: Optional[str] = Query(default=None),
    billing_model: Optional[str] = Query(default=None),
    current_user=Depends(get_current_user),
):
    return scrub_public_sources(await list_compute_offers(
        current_user["_id"], model=model, region=region, billing_model=billing_model,
    ))


@router.get("/energy/prices")
async def energy_prices(
    region: Optional[str] = Query(default=None),
    current_user=Depends(get_current_user),
):
    return scrub_public_sources(await list_energy_prices(current_user["_id"], region=region))


# Persistent operator/fleet state is the Advanced+ fleet-modeling entitlement.
@router.post("/assets", status_code=201)
async def create_asset(
    payload: Dict[str, Any],
    current_user=Depends(require_feature("mining_fleet")),
):
    try:
        return await assets.create_asset(payload, current_user["_id"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/assets")
async def get_assets(
    active_only: bool = Query(default=False),
    current_user=Depends(require_feature("mining_fleet")),
):
    rows = await assets.list_assets(current_user["_id"], active_only=active_only)
    return {"count": len(rows), "assets": rows}


@router.get("/assets/summary")
async def asset_summary(current_user=Depends(require_feature("mining_fleet"))):
    return await assets.fleet_summary(current_user["_id"])


@router.patch("/assets/{asset_id}")
async def patch_asset(
    asset_id: str,
    payload: Dict[str, Any],
    current_user=Depends(require_feature("mining_fleet")),
):
    try:
        row = await assets.update_asset(asset_id, payload, current_user["_id"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    return row


@router.post("/assets/import")
async def import_assets(
    payload: Dict[str, Any],
    current_user=Depends(require_feature("mining_fleet")),
):
    try:
        return await assets.import_assets(payload, current_user["_id"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/retire")
async def retire_asset(
    asset_id: str,
    current_user=Depends(require_feature("mining_fleet")),
):
    row = await assets.retire_asset(asset_id, current_user["_id"])
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    return row


@router.post("/assets/{asset_id}/reactivate")
async def reactivate_asset(
    asset_id: str,
    current_user=Depends(require_feature("mining_fleet")),
):
    row = await assets.reactivate_asset(asset_id, current_user["_id"])
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    return row
