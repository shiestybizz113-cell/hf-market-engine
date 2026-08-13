"""
Mining Intelligence API — read-only mining economics + fleet intelligence.

Every endpoint returns numbers with full provenance (network source, BTC price
provider, simulation flag) and persists an evidence receipt. Honesty contract:
  live mode -> if BTC price or network data is unavailable, the endpoint
               returns 503 unavailable — never a synthetic live number.
  demo mode -> everything is labeled simulation=true.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException

from app.core import ai
from app.core.mining import (
    ASIC_CATALOG, asic_for, compute_estimate, fleet_estimate,
    mine_vs_buy as core_mine_vs_buy, network_data_dict, scenario_table,
)
from app.core.plans import require_feature, has_feature, try_consume_ai_review
from app.models.schemas import (
    AsicModelInfo, MiningEstimateRequest, MiningEstimateResult,
    MineVsBuyRequest, MineVsBuyResult, MiningScenarioRequest, MiningScenarioResult,
    MiningFleetRequest, MiningFleetResult, MiningNetworkData,
)
from app.services.mining_data import mining_data_service
from app.core.database import get_db
from app.api.auth import get_current_user

router = APIRouter(prefix="/mining", tags=["mining"])

_DISCLAIMER = (
    "Read-only economics. Not financial advice. Operating economics only — "
    "hardware, hosting, downtime, resale and horizon assumptions are not "
    "included unless stated. No ROI figure is provided without a full capital basis."
)


def _catalog_item(model: str, custom: Optional[Dict] = None) -> Dict:
    if model:
        item = asic_for(model)
        if item:
            return {
                "model": model,
                "name": item["model"],
                "hashrate_ths": item["hashrate_ths"],
                "power_watts": item["power_watts"],
                "price_usd": item["price_usd"],
                "class": item.get("class"),
            }
        raise HTTPException(status_code=400, detail=f"Unknown ASIC model '{model}'")
    if custom and custom.get("hashrate_ths") and custom.get("power_watts"):
        return {
            "model": "custom",
            "name": "Custom rig",
            "hashrate_ths": custom["hashrate_ths"],
            "power_watts": custom["power_watts"],
            "price_usd": custom.get("hardware_cost_usd") or 0.0,
            "class": "custom",
        }
    raise HTTPException(status_code=400, detail="Provide asic_model or hashrate_ths + power_watts")


async def _live_context() -> Tuple[object, float, bool, Dict]:
    """Return (network, btc_price, simulation, provenance)."""
    network = await mining_data_service.network()
    btc_quote = await mining_data_service.btc_price()
    if mining_data_service.is_demo():
        if network is None or btc_quote is None:
            raise HTTPException(status_code=503, detail="Demo network/price unavailable")
        return network, btc_quote.price, True, {"provider": btc_quote.provider, "source": btc_quote.source}
    if network is None:
        raise HTTPException(status_code=503, detail="Live network data unavailable — no profitability claim made.")
    if btc_quote is None:
        raise HTTPException(status_code=503, detail="Live BTC price unavailable — no profitability claim made.")
    return network, btc_quote.price, False, {"provider": btc_quote.provider, "source": btc_quote.source}


async def _persist_mining_receipt(
    *, user_id: str, analysis_type: str, simulation: bool, flat: Dict,
    observed: Optional[Dict] = None, assumptions: Optional[Dict] = None,
) -> str:
    db = get_db()
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "analysis_type": analysis_type,
        "simulation": simulation,
        "observed_at": datetime.now(timezone.utc),
        "disclaimer": _DISCLAIMER,
    }
    doc.update(flat)
    if observed is not None:
        doc["observed"] = observed
    if assumptions is not None:
        doc["assumptions"] = assumptions
    await db.mining_receipts.insert_one(doc)
    return doc["_id"]


def _estimate_flat(
    asic: Dict, btc_price: float, btc_provider: str, network, est: Dict,
    *, electricity_usd_kwh: float, pool_fee_pct: float, uptime_pct: float,
) -> Dict:
    return {
        "btc_price": btc_price,
        "btc_price_provider": btc_provider,
        "network_hashrate": network.hashrate_ths,
        "difficulty": network.difficulty,
        "block_subsidy": network.block_subsidy,
        "pool_fee_pct": pool_fee_pct,
        "asic_model": asic.get("model"),
        "hashrate_ths": asic["hashrate_ths"],
        "power_watts": asic["power_watts"],
        "electricity_usd_kwh": electricity_usd_kwh,
        "uptime_pct": uptime_pct,
        "estimated_btc_day": est["daily_btc"],
        "estimated_revenue_day": est["revenue_day"],
        "estimated_power_cost_day": est["power_cost_day"],
        "estimated_profit_day": est["operating_profit_day"],
    }


@router.get("/asic-catalog", response_model=list[AsicModelInfo])
async def asic_catalog():
    out = []
    for key, item in ASIC_CATALOG.items():
        out.append(AsicModelInfo(
            model=key,
            name=item["model"],
            hashrate_ths=item["hashrate_ths"],
            power_watts=item["power_watts"],
            price_usd=item["price_usd"],
            efficiency_j_per_ths=round(item["power_watts"] / item["hashrate_ths"], 1),
            class_=item.get("class"),
        ))
    return out


@router.get("/network", response_model=MiningNetworkData)
async def network():
    network = await mining_data_service.network()
    if network is None:
        raise HTTPException(status_code=503, detail="Live network data unavailable.")
    return MiningNetworkData(**network_data_dict(network))


@router.post("/estimate", response_model=MiningEstimateResult)
async def estimate(
    payload: MiningEstimateRequest,
    current_user=Depends(require_feature("mining_economics")),
):
    asic = _catalog_item(payload.asic_model, payload.model_dump())
    network, btc_price, simulation, prov = await _live_context()

    # Evidence integrity: a user-entered BTC price is NOT an observed market
    # observation. It must be labeled user_input, never the live provider.
    if payload.btc_price is not None:
        effective_price = payload.btc_price
        price_provider = "user_input"
        price_observed = False
    else:
        effective_price = btc_price
        price_provider = prov["provider"]
        price_observed = True

    est = compute_estimate(
        hashrate_ths=asic["hashrate_ths"],
        power_watts=asic["power_watts"],
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        btc_price=effective_price,
        hardware_cost_usd=asic["price_usd"],
        network=network,
    )

    flat = _estimate_flat(
        asic, effective_price, price_provider, network, est,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
    )
    observed = {
        "btc_price": effective_price,
        "btc_price_provider": price_provider,
        "btc_price_observed": price_observed,
        "network": network_data_dict(network),
    }
    assumptions = {
        "electricity_usd_kwh": payload.electricity_usd_kwh,
        "pool_fee_pct": payload.pool_fee_pct,
        "uptime_pct": payload.uptime_pct,
        "hardware_cost_usd": asic["price_usd"],
        "hardware_resale_value_usd": 0,
    }
    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="bitcoin_mining_profitability",
        simulation=simulation,
        flat=flat,
        observed=observed,
        assumptions=assumptions,
    )

    ai_review = None
    if has_feature(current_user.get("plan", "free"), "mining_analysis"):
        if await try_consume_ai_review(current_user):
            context = {
                "asic": asic,
                "btc_price": flat["btc_price"],
                "btc_price_provider": price_provider,
                "btc_price_observed": price_observed,
                "electricity_usd_kwh": payload.electricity_usd_kwh,
                "pool_fee_pct": payload.pool_fee_pct,
                "uptime_pct": payload.uptime_pct,
                "network": network_data_dict(network),
                "estimates": est,
            }
            ai_review = await ai.mining_review_for(
                context, user_id=current_user["_id"], simulation=simulation
            )

    return MiningEstimateResult(
        simulation=simulation,
        asic=asic,
        btc_price=flat["btc_price"],
        btc_price_provider=price_provider,
        network=MiningNetworkData(**network_data_dict(network)),
        estimates=est,
        ai_review=ai_review,
        receipt_id=receipt_id,
    )


@router.post("/mine-vs-buy", response_model=MineVsBuyResult)
async def mine_vs_buy(
    payload: MineVsBuyRequest,
    current_user=Depends(require_feature("mining_analysis")),
):
    asic = _catalog_item(payload.asic_model, {})
    network, btc_price, simulation, prov = await _live_context()

    result = core_mine_vs_buy(
        capital_usd=payload.capital_usd,
        asic=asic,
        btc_price=btc_price,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        horizon_days=payload.horizon_days,
        difficulty_growth_pct_year=payload.difficulty_growth_pct_year,
        btc_price_at_horizon=payload.btc_price_at_horizon or btc_price,
        network=network,
        setup_cost_usd_per_unit=payload.setup_cost_usd_per_unit,
        hosting_cost_usd_per_unit_month=payload.hosting_cost_usd_per_unit_month,
        maintenance_cost_usd_per_unit_month=payload.maintenance_cost_usd_per_unit_month,
        hardware_resale_value_usd_per_unit=payload.hardware_resale_value_usd_per_unit,
    )
    result["asic"] = asic
    result["simulation"] = simulation
    result["observed"]["btc_price_provider"] = prov["provider"]
    result["observed"]["btc_price_observed"] = True

    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="bitcoin_mining_mine_vs_buy",
        simulation=simulation,
        flat={
            "btc_price": result["observed"]["btc_price"],
            "btc_price_provider": prov["provider"],
            "network_hashrate": network.hashrate_ths,
            "difficulty": network.difficulty,
            "block_subsidy": network.block_subsidy,
            "asic_model": asic.get("model"),
            "hashrate_ths": asic["hashrate_ths"],
            "power_watts": asic["power_watts"],
            "capital_usd": payload.capital_usd,
        },
        observed=result["observed"],
        assumptions=result["assumptions"],
    )

    ai_review = None
    if await try_consume_ai_review(current_user):
        ai_review = await ai.mine_vs_buy_review_for(
            {
                "capital_usd": payload.capital_usd,
                "btc_price": btc_price,
                "btc_price_provider": prov["provider"],
                "buy_path": result["buy_path"],
                "mining_path": result["mining_path"],
                "assumptions": result["assumptions"],
                "verdict": result["verdict"],
                "break_even_price_at_horizon": result["break_even_price_at_horizon"],
            },
            user_id=current_user["_id"],
            simulation=simulation,
        )

    return MineVsBuyResult(
        simulation=simulation,
        asic=asic,
        observed=result["observed"],
        assumptions=result["assumptions"],
        buy_path=result["buy_path"],
        mining_path=result["mining_path"],
        break_even_price_at_horizon=result["break_even_price_at_horizon"],
        verdict=result["verdict"],
        ai_review=ai_review,
        receipt_id=receipt_id,
    )


@router.post("/scenarios", response_model=MiningScenarioResult)
async def scenarios(
    payload: MiningScenarioRequest,
    current_user=Depends(require_feature("mining_analysis")),
):
    asic = _catalog_item(payload.asic_model, payload.model_dump())
    network, btc_price, simulation, prov = await _live_context()
    est = compute_estimate(
        hashrate_ths=asic["hashrate_ths"],
        power_watts=asic["power_watts"],
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        btc_price=btc_price,
        hardware_cost_usd=asic["price_usd"],
        network=network,
    )
    base = {"network": network_data_dict(network)}

    rows = scenario_table(
        base=base,
        btc_price=btc_price,
        price_shifts_pct=payload.price_shifts_pct,
        difficulty_shifts_pct=payload.difficulty_shifts_pct,
        difficulty=network.difficulty,
        hashrate_ths=asic["hashrate_ths"],
        uptime_pct=payload.uptime_pct,
        pool_fee_pct=payload.pool_fee_pct,
        electricity_usd_kwh=payload.electricity_usd_kwh,
        power_watts=asic["power_watts"],
        hardware_cost_usd=asic["price_usd"],
    )

    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="bitcoin_mining_scenario",
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
        },
        observed={"btc_price": btc_price, "network": network_data_dict(network)},
        assumptions={
            "electricity_usd_kwh": payload.electricity_usd_kwh,
            "pool_fee_pct": payload.pool_fee_pct,
            "uptime_pct": payload.uptime_pct,
            "price_shifts_pct": payload.price_shifts_pct,
            "difficulty_shifts_pct": payload.difficulty_shifts_pct,
        },
    )

    return MiningScenarioResult(
        simulation=simulation,
        network=MiningNetworkData(**network_data_dict(network)),
        scenarios=rows,
        receipt_id=receipt_id,
    )


@router.post("/fleet", response_model=MiningFleetResult)
async def fleet(
    payload: MiningFleetRequest,
    current_user=Depends(require_feature("mining_fleet")),
):
    asic = _catalog_item(payload.asic_model, payload.model_dump())
    network, btc_price, simulation, prov = await _live_context()

    fe = fleet_estimate(
        units=payload.units,
        hashrate_ths=asic["hashrate_ths"],
        power_watts=asic["power_watts"],
        hardware_cost_usd=asic["price_usd"],
        electricity_usd_kwh=payload.electricity_usd_kwh,
        pool_fee_pct=payload.pool_fee_pct,
        uptime_pct=payload.uptime_pct,
        btc_price=btc_price,
        network=network,
    )

    receipt_id = await _persist_mining_receipt(
        user_id=current_user["_id"],
        analysis_type="bitcoin_mining_fleet",
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
            "units": payload.units,
            "estimated_btc_day": fe["daily_btc"],
            "estimated_revenue_day": fe["revenue_day"],
            "estimated_power_cost_day": fe["power_cost_day"],
            "estimated_profit_day": fe["operating_profit_day"],
        },
        observed={"btc_price": btc_price, "network": network_data_dict(network)},
        assumptions={
            "electricity_usd_kwh": payload.electricity_usd_kwh,
            "pool_fee_pct": payload.pool_fee_pct,
            "uptime_pct": payload.uptime_pct,
            "hardware_cost_per_unit_usd": asic["price_usd"],
        },
    )

    return MiningFleetResult(
        simulation=simulation,
        network=MiningNetworkData(**network_data_dict(network)),
        asic=asic,
        estimates=fe,
        receipt_id=receipt_id,
    )


@router.get("/receipts")
async def mining_receipts(limit: int = 20, current_user=Depends(get_current_user)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    db = get_db()
    cursor = (
        db.mining_receipts.find({"user_id": current_user["_id"]})
        .sort("observed_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        doc["id"] = doc.pop("_id")
        out.append(doc)
    return {"count": len(out), "receipts": out}
