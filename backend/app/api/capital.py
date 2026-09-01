"""
Capital Allocation Command Center API — V2 (Evidence Fabric).

One canonical run across the four lanes (BTC treasury, Bitcoin mining, AI/GPU
compute, Energy/storage) on a single normalized economic frame, a scenario
matrix, and a proposal-only optimizer. The AI Capital Council reviews every run.

Evidence V2 contract:
    Every number that enters the engine is an immutable evidence fact.
    Live providers (BTC price, mining network) are OBSERVED_LIVE facts.
    Operator inputs and catalog references are USER_ASSUMPTION facts.
    Each receipt references every fact it consumed. The proof drawer
    reconstructs the full graph from receipt -> facts -> providers -> sources.
    Conflicts and stale data are surfaced, never hidden.

Every run persists an evidence receipt with evidence_ids and per-lane
evidence quality summaries.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.mining import _catalog_item, _live_context, _persist_mining_receipt
from app.core import ai
from app.core import assets as A
from app.core import evidence as E
from app.core.capital_allocation import (
    RISK_PROFILES,
    SCENARIO_DEFS,
    propose_allocation,
    run_capital_allocation,
    run_capital_scenarios,
)
from app.core.database import get_db
from app.core.evidence_broker import capture_observation, lane_evidence
from app.core.plans import has_feature, require_feature, try_consume_ai_review
from app.models.schemas import (
    CapitalOptimizeRequest,
    CapitalOptimizeResult,
    CapitalRunRequest,
    CapitalRunResult,
    CapitalScenarioRequest,
    CapitalScenarioResult,
    CapitalScenarioRow,
)

router = APIRouter(prefix="/capital", tags=["capital"])

_DISCLAIMER = (
    "Read-only research. The optimizer proposes an allocation and never trades, "
    "spends, or deploys capital. BTC price and the mining network are the only "
    "live-observed inputs; GPU, energy and horizon economics are operator "
    "assumptions. No ROI figure is produced without a full capital basis."
)


def _resolve_asic(payload: CapitalRunRequest) -> dict:
    custom = payload.model_dump()
    try:
        return _catalog_item(payload.asic_model or "", custom)
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Provide asic_model or hashrate_ths + power_watts for the mining lane.",
        )


async def _capture_run_facts(
    payload: CapitalRunRequest,
    network, btc_price: float, prov: dict, simulation: bool,
    user_id: str,
) -> tuple[list, dict[str, dict]]:
    """Capture all run inputs as evidence facts and return (evidence_ids, resolutions).

    Returns (all_evidence_ids, metric_resolutions) where resolutions maps
    metric_name -> E.summarize_resolution() shape for per-lane evidence.
    """
    db = get_db()
    all_ids: list[str] = []
    resolutions: dict[str, dict] = {}

    # 1. Live BTC price fact
    btc_eid = await capture_observation(
        domain="market", metric="btc_price", subject_id="BTC",
        value=btc_price, unit="usd",
        state=E.OBSERVED_LIVE if not simulation else E.SIMULATION,
        provider=prov["provider"], source_type=prov["source"],
        _db=db,
    )
    all_ids.append(btc_eid)
    resolutions["btc_price"] = E.summarize_resolution(
        await E.eligible_facts(
            domain="market", metric="btc_price", subject_id="BTC",
            user_id=user_id, _db=db,
        )
    )

    # 2. User-override BTC price (if provided)
    if payload.btc_price is not None:
        eid = await capture_observation(
            domain="market", metric="btc_price", subject_id="BTC",
            value=payload.btc_price, unit="usd",
            state=E.USER_ASSUMPTION, provider="user_input",
            source_type="user_input", user_id=user_id, _db=db,
        )
        all_ids.append(eid)

    # 3. Horizon price assumption
    if payload.btc_price_at_horizon is not None:
        eid = await capture_observation(
            domain="market", metric="btc_price_at_horizon", subject_id="BTC",
            value=payload.btc_price_at_horizon, unit="usd",
            state=E.USER_ASSUMPTION, provider="user_input",
            source_type="user_input", user_id=user_id, _db=db,
        )
        all_ids.append(eid)

    # 4. Network facts
    if network is not None:
        for metric, value, unit in [
            ("network_hashrate", network.hashrate_ths, "ths"),
            ("network_difficulty", network.difficulty, "unitless"),
            ("block_subsidy", network.block_subsidy, "btc"),
        ]:
            eid = await capture_observation(
                domain="mining", metric=metric, subject_id="bitcoin_network",
                value=float(value), unit=unit,
                state=E.OBSERVED_LIVE if not simulation else E.SIMULATION,
                provider=prov["provider"], source_type=prov["source"],
                _db=db,
            )
            all_ids.append(eid)
            resolutions[metric] = E.summarize_resolution(
                await E.eligible_facts(
                    domain="mining", metric=metric, subject_id="bitcoin_network",
                    user_id=user_id, _db=db,
                )
            )

    # 5. Operator-assumption inputs as evidence facts
    assumption_inputs = {
        ("mining", "electricity_usd_kwh"): payload.electricity_usd_kwh,
        ("mining", "pool_fee_pct"): payload.pool_fee_pct,
        ("mining", "uptime_pct"): payload.uptime_pct,
        ("hardware", "asic_price"): payload.hardware_cost_usd,
    }
    for (domain, metric), value in assumption_inputs.items():
        if value is not None:
            eid = await capture_observation(
                domain=domain, metric=metric, subject_id=payload.asic_model or "custom",
                value=float(value),
                unit="usd_kwh" if "electricity" in metric else "pct" if "fee" in metric or "uptime" in metric else "usd",
                state=E.USER_ASSUMPTION, provider="user_input",
                source_type="user_input", user_id=user_id, _db=db,
            )
            all_ids.append(eid)

    return all_ids, resolutions


async def _build_lane_evidence_from_resolutions(
    resolutions: dict[str, dict],
) -> dict[str, dict]:
    """Build per-lane evidence summaries from metric resolutions."""
    btc_metrics = {}
    if "btc_price" in resolutions:
        btc_metrics["btc_price"] = resolutions["btc_price"]
    btc_lane_ev = await lane_evidence(
        lane_key="btc", label="Buy BTC (spot treasury)",
        resolutions=btc_metrics,
    )

    mining_metrics = {}
    for m in ("btc_price", "network_hashrate", "network_difficulty", "block_subsidy"):
        if m in resolutions:
            mining_metrics[m] = resolutions[m]
    mining_lane_ev = await lane_evidence(
        lane_key="mining", label="Bitcoin mining (ASICs)",
        resolutions=mining_metrics,
    )

    # GPU and energy: no live facts yet (all assumptions), but track them.
    gpu_lane_ev = await lane_evidence(
        lane_key="gpu", label="AI / GPU compute (build)",
        resolutions={},
    )
    energy_lane_ev = await lane_evidence(
        lane_key="energy", label="Energy / storage",
        resolutions={},
    )

    return {
        "btc": btc_lane_ev,
        "mining": mining_lane_ev,
        "gpu": gpu_lane_ev,
        "energy": energy_lane_ev,
    }


async def _persist_capital_receipt(
    *, user_id: str, analysis_type: str, simulation: bool, result: dict,
    evidence_ids: list | None = None, lanes_evidence: dict | None = None,
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
        evidence_ids=evidence_ids,
        lanes_evidence=lanes_evidence,
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

    # Capture every input as an evidence fact.
    evidence_ids, resolutions = await _capture_run_facts(
        payload, network, btc_price, prov, simulation, current_user["_id"],
    )

    # Compute fleet summary for this operator.
    fleet = await A.fleet_summary(current_user["_id"], _db=get_db())

    asic = _resolve_asic(payload)
    result = run_capital_allocation(
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
        owned=fleet,
    )
    result["observed"]["btc_price_observed"] = payload.btc_price is None and not simulation

    # Build per-lane evidence summaries.
    lanes_evidence_data = await _build_lane_evidence_from_resolutions(resolutions)

    # Attach evidence to receipt.
    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_run",
        simulation=simulation,
        result=result,
        evidence_ids=evidence_ids,
        lanes_evidence=lanes_evidence_data,
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
                "evidence_ids": evidence_ids,
                "lanes_evidence": lanes_evidence_data,
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
    evidence_ids, resolutions = await _capture_run_facts(
        payload.run, network, btc_price, prov, simulation, current_user["_id"],
    )
    fleet = await A.fleet_summary(current_user["_id"], _db=get_db())

    base = run_capital_allocation(
        capital_usd=payload.run.capital_usd,
        available_mw=payload.run.available_mw,
        horizon_months=payload.run.horizon_months,
        electricity_usd_kwh=payload.run.electricity_usd_kwh,
        risk_profile=payload.run.risk_profile,
        network=network,
        btc_price=payload.run.btc_price or btc_price,
        btc_price_provider=prov["provider"] if payload.run.btc_price is None else "user_input",
        simulation=simulation,
        asic=_resolve_asic(payload.run),
        pool_fee_pct=payload.run.pool_fee_pct,
        uptime_pct=payload.run.uptime_pct,
        btc_price_at_horizon=payload.run.btc_price_at_horizon,
        difficulty_growth_pct_year=payload.run.difficulty_growth_pct_year,
        gpu_model=payload.run.gpu_model or "",
        gpu_capex_usd=payload.run.gpu_capex_usd,
        gpu_power_kw=payload.run.gpu_power_kw,
        gpu_cloud_rental_usd_per_hr=payload.run.gpu_cloud_rental_usd_per_hr,
        gpu_rental_usd_per_hr=payload.run.gpu_rental_usd_per_hr,
        gpu_utilization_pct=payload.run.gpu_utilization_pct,
        gpu_uptime_pct=payload.run.gpu_uptime_pct,
        gpu_units_cap=payload.run.gpu_units_cap,
        gpu_pue=payload.run.gpu_pue,
        energy_acquisition_usd_kwh=payload.run.energy_acquisition_usd_kwh,
        energy_sell_price_usd_kwh=payload.run.energy_sell_price_usd_kwh,
        energy_utilization_pct=payload.run.energy_utilization_pct,
        storage_mwh=payload.run.storage_mwh,
        storage_capex_usd_per_mwh=payload.run.storage_capex_usd_per_mwh,
        storage_roundtrip_pct=payload.run.storage_roundtrip_pct,
        cash_interest_rate_pct_year=payload.run.cash_interest_rate_pct_year,
        owned=fleet,
    )

    keys = payload.vectors or list(SCENARIO_DEFS.keys())
    vectors: list[dict] = []
    for key in keys:
        vec = SCENARIO_DEFS.get(key)
        if not vec:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario '{key}'. Choose from: {', '.join(SCENARIO_DEFS)}",
            )
        vectors.append(vec)

    matrix = run_capital_scenarios(base=base, vectors=vectors)
    lanes_evidence_data = await _build_lane_evidence_from_resolutions(resolutions)

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_scenarios",
        simulation=simulation,
        result=base,
        evidence_ids=evidence_ids,
        lanes_evidence=lanes_evidence_data,
    )

    return CapitalScenarioResult(
        base=base,
        matrix=[CapitalScenarioRow(**row) for row in matrix],
        scenario_keys=keys,
        disclaimer=_DISCLAIMER,
        receipt_id=receipt_id,
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
    evidence_ids, resolutions = await _capture_run_facts(
        default_run, network, btc_price, prov, simulation, current_user["_id"],
    )
    fleet = await A.fleet_summary(current_user["_id"], _db=get_db())

    base = run_capital_allocation(
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        horizon_months=payload.horizon_months,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        risk_profile="balanced",
        network=network,
        btc_price=btc_price,
        btc_price_provider=prov["provider"],
        simulation=simulation,
        asic=_resolve_asic(default_run),
        pool_fee_pct=1.0,
        uptime_pct=95.0,
        btc_price_at_horizon=None,
        difficulty_growth_pct_year=20.0,
        gpu_model="",
        gpu_capex_usd=None,
        gpu_power_kw=None,
        gpu_cloud_rental_usd_per_hr=None,
        gpu_rental_usd_per_hr=None,
        gpu_utilization_pct=85.0,
        gpu_uptime_pct=100.0,
        gpu_units_cap=256,
        gpu_pue=1.3,
        energy_acquisition_usd_kwh=None,
        energy_sell_price_usd_kwh=None,
        energy_utilization_pct=100.0,
        storage_mwh=0.0,
        storage_capex_usd_per_mwh=0.0,
        storage_roundtrip_pct=85.0,
        cash_interest_rate_pct_year=4.0,
        owned=fleet,
    )

    lanes_evidence_data = await _build_lane_evidence_from_resolutions(resolutions)

    proposals: dict[str, dict] = {}
    for profile in profiles:
        base["recommendation"] = propose_allocation(
            capital_usd=payload.capital_usd,
            lanes=base["lanes"],
            risk_profile=profile,
            evidence=lanes_evidence_data,
        )
        proposals[profile] = {
            "proposed_pct": base["recommendation"]["proposed_pct"],
            "proposed_usd": base["recommendation"]["proposed_usd"],
            "basis": base["recommendation"]["basis"],
            "evidence": base["recommendation"].get("evidence", {}),
            "reserve_pct": RISK_PROFILES[profile]["reserve_pct"],
            "treasury_floor_pct": RISK_PROFILES[profile]["treasury_floor_pct"],
        }

    receipt_id = await _persist_capital_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation_optimize",
        simulation=simulation,
        result=base,
        evidence_ids=evidence_ids,
        lanes_evidence=lanes_evidence_data,
    )

    return CapitalOptimizeResult(
        base=base,
        proposals=proposals,
        disclaimer=_DISCLAIMER,
        receipt_id=receipt_id,
    )
