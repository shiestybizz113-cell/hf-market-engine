"""Capital Allocation Command Center V2 API.

One canonical economic frame across BTC treasury, Bitcoin mining, AI/GPU
compute, and energy/storage. Every economically material input is linked to an
immutable evidence fact before the calculation is exposed to the user.

The optimizer PROPOSES only. There is no trade/spend/deploy capability here.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.mining import _catalog_item, _live_context
from app.core import ai
from app.core.capital_allocation import RISK_PROFILES, SCENARIO_DEFS, _rank_lanes, propose_allocation, run_capital_allocation
from app.core.capital_evidence import apply_evidence_to_result, prepare_capital_evidence
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.capital_scenarios_v2 import run_capital_scenarios_v2
from app.core.database import get_db
from app.core.plans import has_feature, require_feature, try_consume_ai_review
from app.models.schemas import CapitalRunRequest, CapitalScenarioRequest

router = APIRouter(prefix="/capital", tags=["capital"])

_DISCLAIMER = (
    "Read-only research and capital-allocation intelligence. The optimizer proposes "
    "only and cannot trade, spend, or deploy capital. Every lane exposes its evidence "
    "quality; provider observations, operator inputs, reference data, simulations, "
    "stale facts and conflicts are never silently collapsed into a fake live result."
)


def _resolve_asic(payload: CapitalRunRequest) -> Dict:
    custom = payload.model_dump()
    try:
        return _catalog_item(payload.asic_model or "", custom)
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Provide asic_model or hashrate_ths + power_watts for the mining lane.",
        )


def _empty_owned_summary() -> Dict:
    return {
        "asics": {"units": 0, "hashrate_ths": 0.0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "gpus": {"units": 0, "power_kw": 0.0, "value_usd": 0.0, "models": []},
        "power_mw": 0.0,
        "storage_mwh": 0.0,
        "treasury_btc": 0.0,
        "treasury_usd": 0.0,
        "total_value_usd": 0.0,
        "asset_count": 0,
        "evidence_ids": [],
        "entitled": False,
        "note": "Persistent owned-fleet modeling requires Advanced+.",
    }


def _enforce_fleet_entitlement(prepared: Dict, current_user: Dict) -> None:
    """Prevent Pro users/downgraded accounts from consuming Advanced fleet state."""
    if has_feature(current_user.get("plan", "free"), "mining_fleet"):
        prepared["owned"]["entitled"] = True
        return

    previous_ids = set(prepared.get("owned", {}).get("evidence_ids", []))
    prepared["evidence_ids"] = [
        evidence_id for evidence_id in prepared.get("evidence_ids", [])
        if evidence_id not in previous_ids
    ]
    prepared["owned"] = _empty_owned_summary()
    prepared.setdefault("context", {})["fleet_entitlement"] = {
        "enabled": False,
        "required_plan": "advanced",
    }


def _proposal_evidence(recommendation: Dict, lanes_evidence: Dict) -> Dict:
    """Describe the evidence quality of lanes that actually receive capital."""
    pct = recommendation.get("proposed_pct", {})
    allocation_key = {
        "btc": "btc_treasury_pct",
        "mining": "bitcoin_mining_pct",
        "gpu": "gpu_compute_pct",
        "energy": "energy_pct",
    }
    per_lane: Dict[str, Dict] = {}
    assumption_heavy: List[str] = []
    active_scores: List[int] = []

    for lane_key, pct_key in allocation_key.items():
        allocated_pct = float(pct.get(pct_key, 0.0) or 0.0)
        lane = lanes_evidence.get(lane_key, {})
        entry = {
            "allocated_pct": allocated_pct,
            "quality_label": lane.get("quality_label", "UNAVAILABLE"),
            "quality_score": int(lane.get("quality_score", 0) or 0),
            "conflict_count": int(lane.get("conflict_count", 0) or 0),
            "facts_used": lane.get("facts_used", []),
        }
        per_lane[lane_key] = entry
        if allocated_pct <= 0:
            continue
        active_scores.append(entry["quality_score"])
        if entry["quality_label"] != "COMPLETE":
            assumption_heavy.append(lane_key)

    label = "EVIDENCE_BACKED" if active_scores and not assumption_heavy else "ASSUMPTION_HEAVY"
    return {
        "label": label,
        "assumption_heavy": label != "EVIDENCE_BACKED",
        "assumption_heavy_lanes": assumption_heavy,
        "active_min_quality_score": min(active_scores) if active_scores else 0,
        "per_lane": per_lane,
        "note": (
            "Recommendation evidence is evaluated only across lanes that receive capital. "
            "Explicit future/operator assumptions remain visible and keep the proposal "
            "ASSUMPTION_HEAVY rather than being mislabeled as fully observed."
        ),
    }


async def _run_prepared(
    *, payload: CapitalRunRequest, current_user: Dict, network, btc_price: float,
    simulation: bool, prov: Dict,
) -> tuple[Dict, Dict]:
    asic = _resolve_asic(payload)
    data = payload.model_dump()

    prepared = await prepare_capital_evidence(
        data=data,
        user_id=current_user["_id"],
        network=network,
        live_btc_price=btc_price,
        provenance=prov,
        simulation=simulation,
        asic=asic,
    )
    _enforce_fleet_entitlement(prepared, current_user)
    effective = prepared["engine"]

    result = run_capital_allocation(
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        horizon_months=payload.horizon_months,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        risk_profile=payload.risk_profile,
        network=network,
        btc_price=float(effective["btc_price"]),
        btc_price_provider=effective["btc_price_provider"],
        simulation=simulation,
        asic=effective["asic"],
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        btc_price_at_horizon=payload.btc_price_at_horizon,
        difficulty_growth_pct_year=payload.difficulty_growth_pct_year,
        gpu_model=payload.gpu_model or "",
        gpu_capex_usd=effective.get("gpu_capex_usd"),
        gpu_power_kw=effective.get("gpu_power_kw"),
        gpu_cloud_rental_usd_per_hr=effective.get("gpu_cloud_rental_usd_per_hr"),
        gpu_rental_usd_per_hr=effective.get("gpu_rental_usd_per_hr"),
        gpu_utilization_pct=payload.gpu_utilization_pct,
        gpu_uptime_pct=payload.gpu_uptime_pct,
        gpu_units_cap=payload.gpu_units_cap,
        gpu_pue=payload.gpu_pue,
        energy_acquisition_usd_kwh=effective.get("energy_acquisition_usd_kwh"),
        energy_sell_price_usd_kwh=effective.get("energy_sell_price_usd_kwh"),
        energy_utilization_pct=payload.energy_utilization_pct,
        storage_mwh=payload.storage_mwh,
        storage_capex_usd_per_mwh=payload.storage_capex_usd_per_mwh,
        storage_roundtrip_pct=payload.storage_roundtrip_pct,
        cash_interest_rate_pct_year=payload.cash_interest_rate_pct_year,
        owned=prepared["owned"],
    )

    apply_energy_storage_integrity(result)
    result["ranking"] = _rank_lanes(result["lanes"])

    result["inputs"]["asic"] = effective["asic"]
    result["inputs"]["gpu_capex_usd"] = effective.get("gpu_capex_usd")
    result["inputs"]["gpu_power_kw"] = effective.get("gpu_power_kw")
    result["inputs"]["gpu_cloud_rental_usd_per_hr"] = effective.get("gpu_cloud_rental_usd_per_hr")
    result["inputs"]["gpu_rental_usd_per_hr"] = effective.get("gpu_rental_usd_per_hr")
    result["inputs"]["energy_acquisition_usd_kwh"] = effective.get("energy_acquisition_usd_kwh")
    result["inputs"]["energy_sell_price_usd_kwh"] = effective.get("energy_sell_price_usd_kwh")

    apply_evidence_to_result(result, prepared)
    recommendation = propose_allocation(
        capital_usd=payload.capital_usd,
        lanes=result["lanes"],
        risk_profile=payload.risk_profile,
        evidence=prepared["lanes"],
    )
    recommendation["evidence"] = _proposal_evidence(recommendation, prepared["lanes"])
    result["recommendation"] = recommendation
    result["owned"]["registry"] = prepared["owned"]
    result["owned"]["fleet_entitled"] = bool(prepared["owned"].get("entitled", False))
    result["disclaimer"] = _DISCLAIMER
    return result, prepared


async def _persist_capital_receipt(
    *, user_id: str, analysis_type: str, simulation: bool, result: Dict,
    prepared: Dict, extra: Dict | None = None,
) -> str:
    db = get_db()
    receipt_id = str(uuid.uuid4())
    doc = {
        "_id": receipt_id,
        "user_id": user_id,
        "analysis_type": analysis_type,
        "simulation": simulation,
        "observed_at": datetime.now(timezone.utc),
        "evidence_ids": prepared["evidence_ids"],
        "lanes_evidence": prepared["lanes"],
        "evidence_quality": prepared["quality"],
        "normalized_inputs": result["inputs"],
        "observed": result["observed"],
        "ranking": result["ranking"],
        "recommendation": result["recommendation"],
        "owned": result.get("owned", {}),
        "disclaimer": _DISCLAIMER,
        "proof_contract": "receipt -> lane -> immutable evidence fact -> source/provider -> snapshot hash",
    }
    if extra:
        doc.update(extra)
    await db.mining_receipts.insert_one(doc)
    return receipt_id


@router.post("/run")
async def capital_run(
    payload: CapitalRunRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    if payload.risk_profile not in RISK_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown risk profile '{payload.risk_profile}'. Choose one of: {', '.join(RISK_PROFILES)}",
        )

    network, btc_price, simulation, prov = await _live_context()
    result, prepared = await _run_prepared(
        payload=payload, current_user=current_user, network=network,
        btc_price=btc_price, simulation=simulation, prov=prov,
    )

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"], analysis_type="capital_allocation_run_v2",
        simulation=simulation, result=result, prepared=prepared,
    )

    ai_review = None
    if has_feature(current_user.get("plan", "free"), "capital_allocation"):
        if await try_consume_ai_review(current_user):
            ai_review = await ai.capital_review_for(
                {**result, "receipt_id": receipt_id},
                user_id=current_user["_id"], simulation=simulation,
            )

    result["ai_review"] = ai_review
    result["receipt_id"] = receipt_id
    return result


@router.post("/scenarios")
async def capital_scenarios(
    payload: CapitalScenarioRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    if payload.run.risk_profile not in RISK_PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown risk profile '{payload.run.risk_profile}'")

    network, btc_price, simulation, prov = await _live_context()
    base, prepared = await _run_prepared(
        payload=payload.run, current_user=current_user, network=network,
        btc_price=btc_price, simulation=simulation, prov=prov,
    )

    keys = payload.vectors or list(SCENARIO_DEFS.keys())
    vectors: List[Dict] = []
    for key in keys:
        vec = SCENARIO_DEFS.get(key)
        if not vec:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario '{key}'. Choose from: {', '.join(SCENARIO_DEFS)}",
            )
        vectors.append(vec)

    matrix = run_capital_scenarios_v2(base=base, vectors=vectors, owned=prepared["owned"])
    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"], analysis_type="capital_allocation_scenarios_v2",
        simulation=simulation, result=base, prepared=prepared,
        extra={"scenario_keys": keys, "scenario_vectors": vectors},
    )

    return {
        "base": base,
        "matrix": matrix,
        "scenario_keys": keys,
        "receipt_id": receipt_id,
        "disclaimer": _DISCLAIMER,
    }


@router.post("/optimize")
async def capital_optimize(
    payload: Dict[str, Any],
    current_user=Depends(require_feature("capital_allocation")),
):
    raw = dict(payload)
    profiles = raw.pop("risk_profiles", None) or list(RISK_PROFILES.keys())
    bad = [p for p in profiles if p not in RISK_PROFILES]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown risk profiles: {bad}. Choose from: {', '.join(RISK_PROFILES)}",
        )

    try:
        default_run = CapitalRunRequest(**raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Capital optimizer inputs: {exc}") from exc

    network, btc_price, simulation, prov = await _live_context()
    base, prepared = await _run_prepared(
        payload=default_run, current_user=current_user, network=network,
        btc_price=btc_price, simulation=simulation, prov=prov,
    )

    proposals: Dict[str, Dict] = {}
    for profile in profiles:
        recommendation = propose_allocation(
            capital_usd=default_run.capital_usd,
            lanes=base["lanes"],
            risk_profile=profile,
            evidence=prepared["lanes"],
        )
        recommendation["evidence"] = _proposal_evidence(recommendation, prepared["lanes"])
        proposals[profile] = {
            "proposed_pct": recommendation["proposed_pct"],
            "proposed_usd": recommendation["proposed_usd"],
            "basis": recommendation["basis"],
            "reserve_pct": RISK_PROFILES[profile]["reserve_pct"],
            "treasury_floor_pct": RISK_PROFILES[profile]["treasury_floor_pct"],
            "evidence": recommendation["evidence"],
        }

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"], analysis_type="capital_allocation_optimize_v2",
        simulation=simulation, result=base, prepared=prepared,
        extra={"optimizer_profiles": profiles, "optimizer_proposals": proposals},
    )

    return {
        "base": base,
        "proposals": proposals,
        "receipt_id": receipt_id,
        "disclaimer": _DISCLAIMER,
    }
