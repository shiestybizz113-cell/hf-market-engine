"""
Hardware Offers API — ASIC quote registry.

Operators post distributor / secondary-market / manufacturer / user-purchase
quotes. Every quote is normalized into an immutable evidence fact (domain
``hardware``, metric ``asic_price``) that the capital engine and the proof
drawer can resolve.

The existing catalog (core.mining.ASIC_CATALOG) remains seeded as reference
facts (source_type ``reference``) — the lowest-quality signal. A distributor
quote outranks it, a user-purchase fact outranks everything except observed
live pricing (which does not exist for hardware).

GET /hardware/offers returns a ranked list of eligible facts for each ASIC
model so the operator can see which fact the capital engine would consume.
"""


from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.core import evidence as E
from app.core.database import get_db
from app.core.evidence_broker import capture_observation
from app.core.mining import ASIC_CATALOG

router = APIRouter(prefix="/hardware", tags=["hardware"])

VALID_SOURCE_TYPES = (
    "distributor_quote", "secondary_market", "manufacturer_reference",
    "user_purchase", "user_assumption", "reference", "user_input",
)


class HardwareQuoteRequest(BaseModel):
    model: str = Field(description="ASIC model key (e.g. S21 Pro) or free text")
    price_usd: float = Field(gt=0)
    currency: str = Field(default="USD")
    source_type: str = Field(default="user_input")
    source_reference: str | None = Field(default=None)
    provider: str = Field(default="user_input", description="Who supplied the quote")
    region: str | None = None
    condition: str | None = Field(default=None, description="new | used | refurbished")
    quantity: int = Field(ge=1, default=1)
    hashrate_ths: float | None = Field(default=None, description="Override spec if known")
    power_watts: float | None = Field(default=None)
    shipping_usd: float | None = Field(default=None)
    observed_at: str | None = Field(default=None, description="ISO timestamp when the quote was observed")


@router.post("/offers")
async def post_hardware_offer(
    body: HardwareQuoteRequest,
    current_user=Depends(get_current_user),
):
    """Post an ASIC quote as an immutable evidence fact."""
    hashrate = body.hashrate_ths
    power = body.power_watts
    if body.model in ASIC_CATALOG:
        cat = ASIC_CATALOG[body.model]
        hashrate = hashrate or cat["hashrate_ths"]
        power = power or cat["power_watts"]
    extra = {"condition": body.condition, "quantity": body.quantity, "shipping_usd": body.shipping_usd}
    eid = await capture_observation(
        domain="hardware",
        metric="asic_price",
        subject_id=body.model,
        value=body.price_usd,
        unit="usd",
        state=E.USER_ASSUMPTION,
        provider=body.provider,
        source_type=body.source_type,
        source_reference=body.source_reference,
        region=body.region,
        user_id=current_user["_id"],
        extra=extra,
        _db=get_db(),
    )
    return {"ok": True, "fact_id": eid, "model": body.model, "price_usd": body.price_usd}


@router.get("/offers")
async def get_hardware_offers(
    model: str | None = None,
    current_user=Depends(get_current_user),
):
    """Ranked eligible facts for ASIC pricing (best-first).

    Always includes reference catalog facts (shared) and any operator-quoted
    facts (user-scoped). Returns full trace + quality per fact.
    """
    db = get_db()
    models = list(ASIC_CATALOG.keys())
    if model:
        models = [m for m in models if model.lower() in m.lower()] or models[:1]
    out = {}
    for m in models:
        cat = ASIC_CATALOG[m]
        facts = await E.eligible_facts(
            domain="hardware", metric="asic_price", subject_id=m,
            user_id=current_user["_id"], _db=db,
        )
        # Always ensure a reference fact from the catalog exists.
        if not any(f.get("source_type") == "reference" for f in facts):
            await capture_observation(
                domain="hardware", metric="asic_price", subject_id=m,
                value=float(cat["price_usd"]), unit="usd",
                state=E.USER_ASSUMPTION, provider="reference_catalog",
                source_type="reference", _db=db,
            )
            facts = await E.eligible_facts(
                domain="hardware", metric="asic_price", subject_id=m,
                user_id=current_user["_id"], _db=db,
            )
        resolution = E.summarize_resolution(facts)
        out[m] = {
            "hashrate_ths": cat["hashrate_ths"],
            "power_watts": cat["power_watts"],
            "resolution": resolution,
        }
    return {"offers": out}


@router.get("/catalog")
async def hardware_catalog():
    """Return the reference ASIC catalog."""
    return {"catalog": list(ASIC_CATALOG.values())}
