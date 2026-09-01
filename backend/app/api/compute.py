"""
Compute Offers API — GPU rental offer registry.

Operators post cloud-provider quotes. Every quote is normalized into an
immutable evidence fact (domain ``gpu``, metric ``compute_offer``) that the
capital engine and proof drawer can resolve.

GET /compute/offers returns ranked eligible facts per GPU model so the
capital engine picks the best cloud rate when the operator has not manually
overridden it.
"""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import evidence as E
from app.core.evidence_broker import capture_observation
from app.core.gpu import GPU_CATALOG
from app.api.auth import get_current_user
from app.core.database import get_db

router = APIRouter(prefix="/compute", tags=["compute"])

VALID_BILLING = ("spot", "on_demand", "reserved")
VALID_AVAILABILITY = ("available", "limited", "preorder")


class ComputeOfferRequest(BaseModel):
    gpu_model: str = Field(description="GPU model key (H100, H200, B200, etc.)")
    provider: str = Field(description="Cloud provider name")
    price_per_gpu_hour: float = Field(gt=0)
    billing: str = Field(default="on_demand")
    region: Optional[str] = None
    quantity: int = Field(ge=1, default=1)
    currency: str = Field(default="USD")
    min_commitment_hours: int = Field(ge=0, default=0)
    availability: str = Field(default="available")
    source_reference: Optional[str] = None
    observed_at: Optional[str] = None


@router.post("/offers")
async def post_compute_offer(
    body: ComputeOfferRequest,
    current_user=Depends(get_current_user),
):
    """Post a cloud GPU rental offer as an immutable evidence fact."""
    cat = GPU_CATALOG.get(body.gpu_model)
    extra = {
        "gpu_model": body.gpu_model,
        "billing": body.billing,
        "quantity": body.quantity,
        "min_commitment_hours": body.min_commitment_hours,
        "availability": body.availability,
        "currency": body.currency,
        "vram_gb": cat.get("vram_gb") if cat else None,
    }
    eid = await capture_observation(
        domain="gpu",
        metric="compute_offer",
        subject_id=body.gpu_model,
        value=body.price_per_gpu_hour,
        unit="usd_hr",
        state=E.USER_ASSUMPTION,
        provider=body.provider,
        source_type="cloud_provider",
        source_reference=body.source_reference,
        region=body.region,
        user_id=current_user["_id"],
        extra=extra,
        _db=get_db(),
    )
    return {
        "ok": True,
        "fact_id": eid,
        "gpu_model": body.gpu_model,
        "provider": body.provider,
        "price_per_gpu_hour": body.price_per_gpu_hour,
    }


@router.get("/offers")
async def get_compute_offers(
    gpu_model: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Ranked eligible facts per GPU model. Always includes reference catalog."""
    db = get_db()
    models = list(GPU_CATALOG.keys())
    if gpu_model:
        models = [m for m in models if gpu_model.lower() in m.lower()] or models[:1]
    out = {}
    for m in models:
        cat = GPU_CATALOG[m]
        facts = await E.eligible_facts(
            domain="gpu", metric="compute_offer", subject_id=m,
            user_id=current_user["_id"], _db=db,
        )
        # Ensure reference rental fact exists.
        if not any(f.get("source_type") == "reference" for f in facts):
            await capture_observation(
                domain="gpu", metric="compute_offer", subject_id=m,
                value=float(cat["cloud_rental_usd_hr"]), unit="usd_hr",
                state=E.USER_ASSUMPTION, provider="reference_catalog",
                source_type="reference", _db=db,
            )
            facts = await E.eligible_facts(
                domain="gpu", metric="compute_offer", subject_id=m,
                user_id=current_user["_id"], _db=db,
            )
        resolution = E.summarize_resolution(facts)
        out[m] = {
            "model": cat["model"],
            "capex_usd": cat["capex_usd"],
            "power_kw": cat["power_kw"],
            "cloud_rental_usd_hr": cat["cloud_rental_usd_hr"],
            "resolution": resolution,
        }
    return {"offers": out}
