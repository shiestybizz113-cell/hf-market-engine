"""
Capital Allocation Command Center API.

One canonical run across the four lanes (BTC treasury, Bitcoin mining, AI/GPU
compute, Energy/storage) on a single normalized economic frame, a scenario
matrix, and a proposal-only optimizer. The AI Capital Council reviews every run.

Evidence contract (same as the rest of the system):
    - BTC price + mining network are live-observed (or labeled demo/simulation).
    - GPU and energy economics are operator assumptions, always labeled as such.
    - The optimizer PROPOSES a split. It never trades, spends or deploys.

Every run persists an evidence receipt separating observed data from assumptions.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException

from app.core import ai
from app.core.capital_allocation import (
    RISK_PROFILES, SCENARIO_DEFS, run_capital_allocation, run_capital_scenarios,
    propose_allocation,
)
from app.core.gpu import GPU_CATALOG
from app.api.mining import _catalog_item, _live_context, _persist_mining_receipt
from app.core.plans import require_feature, has_feature, try_consume_ai_review
from app.models.schemas import (
    CapitalRunRequest, CapitalRunResult, CapitalScenarioRequest,
    CapitalScenarioResult, CapitalScenarioRow, CapitalOptimizeRequest,
    CapitalOptimizeResult,
)
from app.core.database import get_db
from app.api.auth import get_current_user

router = APIRouter(prefix="/capital", tags=["capital"])

_DISCLAIMER = (
    "Read-only research. The optimizer proposes an allocation and never trades, "
    "spends, or deploys capital. BTC price and the mining network are the only "
    "live-observed inputs; GPU, energy and horizon economics are operator "
    "assumptions. No ROI figure is produced without a full capital basis."
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


def _run_engine(payload: CapitalRunRequest, network, btc_price, prov, simulation) -> Dict:
    asic = _resolve_asic(payload)
    return run_capital_allocation(
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        horizon_months=payload.horizon_months,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        risk_profile=payload.risk_profile,
        network=network,
        btc_price=payload.btc_price or btc_price,
        btc_price_provider=prov["provider"] if payload.btc_price is None else "user_input",
        simulation=simulation,
        asic=asic,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        btc_price_at_horizon=payload.btc_price_at_horizon,
        difficulty_growth_pct_year=payload.difficulty_growth_pct_year,
        gpu_model=payload.gpu_model or "",
        gpu_capex_usd=payload.gpu_capex_usd,
        gpu_power_kw=payload.gpu_power_kw,
        gpu_cloud_rental_usd_per_hr=payload.gpu_cloud_rental_usd_per_hr,
        gpu_rental_usd_per_hr=payload.gpu_rental_usd_per_hr,
        gpu_utilization_pct=payload.gpu_utilization_pct,
        gpu_uptime_pct=payload.gpu_uptime_pct,
        gpu_units_cap=payload.gpu_units_cap,
        gpu_pue=payload.gpu_pue,
        energy_acquisition_usd_kwh=payload.energy_acquisition_usd_kwh,
        energy_sell_price_usd_kwh=payload.energy_sell_price_usd_kwh,
        energy_utilization_pct=payload.energy_utilization_pct,
        storage_mwh=payload.storage_mwh,
        storage_capex_usd_per_mwh=payload.storage_capex_usd_per_mwh,
        storage_roundtrip_pct=payload.storage_roundtrip_pct,
        cash_interest_rate_pct_year=payload.cash_interest_rate_pct_year,
    )


async def _persist_capital_receipt(
    *, user_id: str, analysis_type: str, simulation: bool, result: Dict,
) -> str:
    flat = {
        "capital_usd": result["inputs"]["capital_usd"],
        "available_mw": result["inputs"]["available_mw"],
        "horizon_months": result["inputs"]["horizon_months"],
        "risk_profile": result["inputs"]["risk_profile"],
        "ranking": result["ranking"],
        "proposed_pct": result["recommendation"]["proposed_pct"],
        "proposed_usd": result["recommendation"]["proposed_usd"],
    }
    return await _persist_mining_receipt(
        user_id=user_id,
        analysis_type=analysis_type,
        simulation=simulation,
        flat=flat,
        observed=result["observed"],
        assumptions=result["inputs"],
    )


@router.post("/run", response_model=CapitalRunResult)
async def capital_run(
    payload: CapitalRunRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    if payload.risk_profile not in RISK_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown risk profile '{payload.risk_profile}'. "
                   f"Choose one of: {', '.join(RISK_PROFILES)}",
        )
    network, btc_price, simulation, prov = await _live_context()

    result = _run_engine(payload, network, btc_price, prov, simulation)
    result["observed"]["btc_price_observed"] = payload.btc_price is None and not simulation

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_run",
        simulation=simulation,
        result=result,
    )

    ai_review = None
    if has_feature(current_user.get("plan", "free"), "capital_allocation"):
        if await try_consume_ai_review(current_user):
            context = {
                **result,
                "simulation": simulation,
                "capital_usd": payload.capital_usd,
                "available_mw": payload.available_mw,
                "horizon_months": payload.horizon_months,
                "risk_profile": payload.risk_profile,
            }
            ai_review = await ai.capital_review_for(
                context, user_id=current_user["_id"], simulation=simulation,
            )

    return CapitalRunResult(
        simulation=simulation,
        inputs=result["inputs"],
        observed=result["observed"],
        lanes=result["lanes"],
        ranking=result["ranking"],
        ranking_basis=result["ranking_basis"],
        recommendation=result["recommendation"],
        ai_review=ai_review,
        receipt_id=receipt_id,
    )


@router.post("/scenarios", response_model=CapitalScenarioResult)
async def capital_scenarios(
    payload: CapitalScenarioRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    network, btc_price, simulation, prov = await _live_context()
    base = _run_engine(payload.run, network, btc_price, prov, simulation)

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

    matrix = run_capital_scenarios(base=base, vectors=vectors)

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_scenarios",
        simulation=simulation,
        result=base,
    )

    return CapitalScenarioResult(
        base=base,
        matrix=[
            CapitalScenarioRow(**row) for row in matrix
        ],
        scenario_keys=keys,
        disclaimer=_DISCLAIMER,
    )


@router.post("/optimize", response_model=CapitalOptimizeResult)
async def capital_optimize(
    payload: CapitalOptimizeRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    network, btc_price, simulation, prov = await _live_context()

    profiles = payload.risk_profiles or list(RISK_PROFILES.keys())
    bad = [p for p in profiles if p not in RISK_PROFILES]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown risk profiles: {bad}. Choose from: {', '.join(RISK_PROFILES)}",
        )

    # Optimize across profiles using a canonical default run (no BTC override so
    # the proposal uses observed market data).
    default_run = CapitalRunRequest(
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        horizon_months=payload.horizon_months,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        asic_model=payload.asic_model,
        hashrate_ths=payload.hashrate_ths,
        power_watts=payload.power_watts,
        hardware_cost_usd=payload.hardware_cost_usd,
    )
    base = _run_engine(default_run, network, btc_price, prov, simulation)

    proposals: Dict[str, Dict] = {}
    for profile in profiles:
        base["recommendation"] = propose_allocation(
            capital_usd=payload.capital_usd,
            lanes=base["lanes"],
            risk_profile=profile,
        )
        proposals[profile] = {
            "proposed_pct": base["recommendation"]["proposed_pct"],
            "proposed_usd": base["recommendation"]["proposed_usd"],
            "basis": base["recommendation"]["basis"],
            "reserve_pct": RISK_PROFILES[profile]["reserve_pct"],
            "treasury_floor_pct": RISK_PROFILES[profile]["treasury_floor_pct"],
        }

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_optimize",
        simulation=simulation,
        result=base,
    )

    return CapitalOptimizeResult(
        base=base,
        proposals=proposals,
        disclaimer=_DISCLAIMER,
        receipt_id=receipt_id,
    )
