"""
Institutional Decision Layer API — SecDB-style scenarios + capital allocation.

Both engines run on live (or labeled-demo) market + network data and persist
evidence receipts that separate observed data from assumptions. In live mode
missing price/network data returns 503 — never a synthetic live number.
"""

from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException

from app.core import ai
from app.core.scenario import SCENARIO_PRESETS, run_scenario_set
from app.core.allocation import allocate, rank_options
from app.api.mining import _catalog_item, _live_context, _persist_mining_receipt
from app.core.plans import require_feature, has_feature, try_consume_ai_review
from app.models.schemas import (
    ScenarioPreset, ScenarioVector, ScenarioRunRequest, ScenarioRunResult,
    ScenarioRunResultItem, AllocationRequest, AllocationResult, AllocationOption,
    MiningNetworkData,
)
from app.core.mining import network_data_dict
from app.core.database import get_db
from app.api.auth import get_current_user

router = APIRouter(prefix="/decision", tags=["decision"])

RANKING_BASIS = (
    "Ranked by monthly operating flow per capital deployed; zero-capital "
    "options ranked on absolute monthly flow. Excludes risk adjustment, "
    "financing, and horizon — stated basis, not a total-return claim."
)


@router.get("/scenario/presets", response_model=list[ScenarioPreset])
async def scenario_presets():
    return [
        ScenarioPreset(name=name, label=preset["label"], vector={
            k: preset[k] for k in (
                "btc_price_shift_pct", "difficulty_shift_pct",
                "electricity_usd_kwh", "uptime_pct",
            )
        })
        for name, preset in SCENARIO_PRESETS.items()
    ]


@router.post("/scenario/run", response_model=ScenarioRunResult)
async def scenario_run(
    payload: ScenarioRunRequest,
    current_user=Depends(require_feature("scenario_engine")),
):
    asic = _catalog_item(payload.asic_model, payload.model_dump())
    network, btc_price, simulation, prov = await _live_context()

    vectors: List[Dict] = []
    for name in payload.preset_names:
        preset = SCENARIO_PRESETS.get(name)
        if not preset:
            raise HTTPException(status_code=400, detail=f"Unknown scenario preset '{name}'")
        vectors.append({
            "label": preset["label"],
            "btc_price_shift_pct": preset["btc_price_shift_pct"],
            "difficulty_shift_pct": preset["difficulty_shift_pct"],
            "electricity_usd_kwh": preset["electricity_usd_kwh"],
            "uptime_pct": preset["uptime_pct"],
        })
    for s in payload.scenarios:
        vectors.append({
            "label": s.label,
            "btc_price_shift_pct": s.btc_price_shift_pct,
            "difficulty_shift_pct": s.difficulty_shift_pct,
            "electricity_usd_kwh": s.electricity_usd_kwh,
            "uptime_pct": s.uptime_pct,
        })
    if not vectors:
        raise HTTPException(status_code=400, detail="Provide preset_names or scenarios")
    if len(vectors) > payload.max_total:
        raise HTTPException(
            status_code=400,
            detail=f"Too many scenarios ({len(vectors)}), cap is {payload.max_total}",
        )

    results = run_scenario_set(
        asic=asic,
        network=network,
        btc_price=btc_price,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        scenarios=vectors,
    )

    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="scenario_run",
        simulation=simulation,
        flat={
            "btc_price": btc_price,
            "btc_price_provider": prov["provider"],
            "network_hashrate": network.hashrate_ths,
            "difficulty": network.difficulty,
            "block_subsidy": network.block_subsidy,
            "asic_model": asic.get("model"),
            "hashrate_ths": asic["hashrate_ths"],
            "power_watts": asic["power_watts"],
            "pool_fee_pct": payload.pool_fee_pct,
            "scenario_count": len(results),
        },
        observed={"btc_price": btc_price, "network": network_data_dict(network)},
        assumptions={
            "scenarios": [
                {"label": r["label"], **r["vector"]} for r in results
            ],
            "electricity_usd_kwh_base": payload.electricity_usd_kwh,
            "uptime_pct_base": payload.uptime_pct,
        },
    )

    ai_review = None
    if has_feature(current_user.get("plan", "free"), "scenario_engine") \
            and await try_consume_ai_review(current_user):
        ai_review = await ai.scenario_review_for(
            {
                "btc_price": btc_price,
                "network": network_data_dict(network),
                "scenarios": results,
            },
            user_id=current_user["_id"],
            simulation=simulation,
        )

    return ScenarioRunResult(
        simulation=simulation,
        btc_price=btc_price,
        btc_price_provider=prov["provider"],
        network=MiningNetworkData(**network_data_dict(network)),
        asic=asic,
        scenarios=[
            ScenarioRunResultItem(
                label=r["label"],
                vector=r["vector"],
                btc_price=r["btc_price"],
                difficulty=r["difficulty"],
                estimates=r["estimates"],
                risk=r["risk"],
                risk_flags=r["risk_flags"],
            )
            for r in results
        ],
        ai_review=ai_review,
        receipt_id=receipt_id,
    )


@router.post("/allocation/run", response_model=AllocationResult)
async def allocation_run(
    payload: AllocationRequest,
    current_user=Depends(require_feature("capital_allocation")),
):
    asic = _catalog_item(payload.asic_model, payload.model_dump())
    network, btc_price, simulation, prov = await _live_context()

    options = allocate(
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        asic=asic,
        btc_price=btc_price,
        network=network,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        energy_sell_price_usd_kwh=payload.energy_sell_price_usd_kwh,
        cash_interest_rate_pct_year=payload.cash_interest_rate_pct_year,
    )
    ranking = rank_options(options)

    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="capital_allocation",
        simulation=simulation,
        flat={
            "capital_usd": payload.capital_usd,
            "available_mw": payload.available_mw,
            "btc_price": btc_price,
            "btc_price_provider": prov["provider"],
            "network_hashrate": network.hashrate_ths,
            "difficulty": network.difficulty,
            "block_subsidy": network.block_subsidy,
            "ranking": ranking,
            "ranking_basis": RANKING_BASIS,
        },
        observed={"btc_price": btc_price, "network": network_data_dict(network)},
        assumptions={
            "asic_model": asic.get("model"),
            "electricity_usd_kwh": payload.electricity_usd_kwh,
            "pool_fee_pct": payload.pool_fee_pct,
            "uptime_pct": payload.uptime_pct,
            "energy_sell_price_usd_kwh": payload.energy_sell_price_usd_kwh,
            "cash_interest_rate_pct_year": payload.cash_interest_rate_pct_year,
        },
    )

    ai_review = None
    if has_feature(current_user.get("plan", "free"), "capital_allocation") \
            and await try_consume_ai_review(current_user):
        ai_review = await ai.allocation_review_for(
            {
                "capital_usd": payload.capital_usd,
                "available_mw": payload.available_mw,
                "btc_price": btc_price,
                "btc_price_provider": prov["provider"],
                "ranking": ranking,
                "ranking_basis": RANKING_BASIS,
                "options": options,
            },
            user_id=current_user["_id"],
            simulation=simulation,
        )

    return AllocationResult(
        simulation=simulation,
        capital_usd=payload.capital_usd,
        available_mw=payload.available_mw,
        btc_price=btc_price,
        btc_price_provider=prov["provider"],
        network=MiningNetworkData(**network_data_dict(network)),
        asic=asic,
        options=[AllocationOption(**o) for o in options],
        ranking=ranking,
        ranking_basis=RANKING_BASIS,
        ai_review=ai_review,
        receipt_id=receipt_id,
    )


@router.get("/receipts")
async def decision_receipts(limit: int = 20, current_user=Depends(get_current_user)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    db = get_db()
    cursor = (
        db.mining_receipts.find({
            "user_id": current_user["_id"],
            "analysis_type": {"$in": ["scenario_run", "capital_allocation"]},
        })
        .sort("observed_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        doc["id"] = doc.pop("_id")
        out.append(doc)
    return {"count": len(out), "receipts": out}
