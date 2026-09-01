"""
Energy Prices API — power price registry.

Operators post wholesale / tariff / contract prices. Every price is normalized
into an immutable evidence fact (domain ``energy``, metric ``power_price``).

The freshness policy distinguishes:
    wholesale  — grid price, short TTL (5 minutes)
    tariff     — utility rate, 7-day TTL
    contract   — PPA / fixed rate, 30-day TTL
    user_assumption — operator estimate, 90-day TTL

The capital engine uses the best-eligible power_price fact for the energy lane
acquisition cost when the operator has not supplied an explicit override.
"""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import evidence as E
from app.core.evidence_broker import capture_observation
from app.api.auth import get_current_user
from app.core.database import get_db

router = APIRouter(prefix="/energy", tags=["energy"])

VALID_PRICE_TYPES = ("wholesale", "tariff", "contract", "user_assumption")


class EnergyPriceRequest(BaseModel):
    price_usd_kwh: float = Field(gt=0)
    price_type: str = Field(default="user_assumption")
    provider: str = Field(default="user_input")
    region: Optional[str] = None
    source_reference: Optional[str] = None
    demand_charge_usd_kw_month: Optional[float] = Field(default=None, ge=0)
    min_consumption_kwh_day: Optional[float] = Field(default=None, ge=0)
    time_of_use: Optional[str] = Field(default=None, description="peak | off_peak | flat")
    observed_at: Optional[str] = None


@router.post("/prices")
async def post_energy_price(
    body: EnergyPriceRequest,
    current_user=Depends(get_current_user),
):
    """Post a power price as an immutable evidence fact."""
    extra = {
        "demand_charge_usd_kw_month": body.demand_charge_usd_kw_month,
        "min_consumption_kwh_day": body.min_consumption_kwh_day,
        "time_of_use": body.time_of_use,
    }
    eid = await capture_observation(
        domain="energy",
        metric="power_price",
        subject_id="grid_power",
        value=body.price_usd_kwh,
        unit="usd_kwh",
        state=E.USER_ASSUMPTION,
        provider=body.provider,
        source_type=body.price_type,
        source_reference=body.source_reference,
        region=body.region,
        user_id=current_user["_id"],
        extra=extra,
        _db=get_db(),
    )
    return {
        "ok": True,
        "fact_id": eid,
        "price_usd_kwh": body.price_usd_kwh,
        "price_type": body.price_type,
    }


@router.get("/prices")
async def get_energy_prices(
    current_user=Depends(get_current_user),
):
    """Ranked eligible power-price facts (best-first) with quality summary."""
    db = get_db()
    facts = await E.eligible_facts(
        domain="energy", metric="power_price", subject_id="grid_power",
        user_id=current_user["_id"], _db=db,
    )
    resolution = E.summarize_resolution(facts)
    return {"prices": resolution}


@router.get("/price-types")
async def price_types():
    """Available price types and their freshness TTLs."""
    return {
        "types": [
            {"key": "wholesale", "label": "Wholesale / grid", "freshness_seconds": 300},
            {"key": "tariff", "label": "Utility tariff", "freshness_seconds": 7 * 86400},
            {"key": "contract", "label": "PPA / fixed contract", "freshness_seconds": 30 * 86400},
            {"key": "user_assumption", "label": "Operator estimate", "freshness_seconds": 90 * 86400},
        ]
    }
