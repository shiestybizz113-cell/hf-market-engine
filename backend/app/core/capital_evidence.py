"""Evidence-to-engine bridge for Capital Allocation Command Center V2.

This is the institutional contract:
  provider/operator observation -> immutable fact -> resolved input
  -> deterministic Capital calculation -> lane evidence -> receipt/proof graph.

The engine never needs to know how a price was sourced; this module makes sure
the value handed to it is the same value referenced by the evidence receipt.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core import evidence as E
from app.core.assets import fleet_summary
from app.core.evidence_broker import capture_observation, lane_evidence, resolve_metric
from app.core.infrastructure_data import (
    resolve_compute_bundle,
    resolve_energy_market,
    resolve_hardware_bundle,
)


def _now():
    return datetime.now(timezone.utc)


async def _assumption(
    *, user_id: str, domain: str, metric: str, value: Optional[float], unit: str,
    subject_id: str = "operator", methodology: str, extra: Optional[Dict] = None,
) -> Dict:
    if value is None:
        return await resolve_metric(
            domain=domain, metric=metric, subject_id=subject_id, user_id=user_id,
        )
    return await resolve_metric(
        domain=domain,
        metric=metric,
        subject_id=subject_id,
        user_id=user_id,
        explicit_value=float(value),
        explicit_unit=unit,
        explicit_methodology=methodology,
        explicit_extra=extra or {},
    )


async def prepare_capital_evidence(
    *,
    data: Dict[str, Any],
    user_id: str,
    network,
    live_btc_price: float,
    provenance: Dict,
    simulation: bool,
    asic: Dict,
) -> Dict:
    """Resolve all economically material inputs and return engine overrides.

    User/operator state is recorded too, but lane quality focuses on the facts
    that materially determine the economics rather than penalizing a lane just
    because the operator told us how much capital they have.
    """
    # ------------------------------------------------------------------
    # Market + network observations actually used by the run.
    # ------------------------------------------------------------------
    user_btc = data.get("btc_price")
    effective_btc = float(user_btc if user_btc is not None else live_btc_price)
    btc_subject = "BTC:demo" if simulation and user_btc is None else "BTC"

    if user_btc is not None:
        btc_res = await _assumption(
            user_id=user_id, domain="market", metric="btc_price",
            value=effective_btc, unit="usd", subject_id="BTC",
            methodology="Operator-supplied BTC spot price override",
        )
    else:
        await capture_observation(
            domain="market",
            metric="btc_price",
            subject_id=btc_subject,
            value=effective_btc,
            unit="usd",
            state=E.SIMULATION if simulation else E.OBSERVED_LIVE,
            provider=provenance.get("provider", "unknown"),
            source_type="demo" if simulation else "live_api",
            source_reference=provenance.get("source"),
            observed_at=_now(),
            methodology="BTC spot observation used by Capital run",
            extra={"asset": "BTC", "market_data_mode": "demo" if simulation else "live"},
        )
        btc_res = await resolve_metric(
            domain="market", metric="btc_price", subject_id=btc_subject, user_id=user_id,
        )

    network_subject = "bitcoin_network:demo" if simulation else "bitcoin_network"
    if network is not None:
        network_state = E.SIMULATION if simulation else E.OBSERVED_LIVE
        network_source_type = "demo" if simulation else "live_api"
        network_provider = getattr(network, "provider", "unknown")
        network_source = getattr(network, "source", None)
        observed_at = getattr(network, "observed_at", None) or _now()
        for metric, value, unit in (
            ("network_hashrate", getattr(network, "hashrate_ths", None), "ths"),
            ("network_difficulty", getattr(network, "difficulty", None), "difficulty"),
            ("block_subsidy", getattr(network, "block_subsidy", None), "btc_block"),
        ):
            if value is None:
                continue
            await capture_observation(
                domain="mining", metric=metric, subject_id=network_subject,
                value=float(value), unit=unit, state=network_state,
                provider=network_provider, source_type=network_source_type,
                source_reference=network_source, observed_at=observed_at,
                methodology="Bitcoin network observation used by Capital run",
                extra={"network": "bitcoin"},
            )

    network_hashrate = await resolve_metric(
        domain="mining", metric="network_hashrate", subject_id=network_subject, user_id=user_id,
    )
    network_difficulty = await resolve_metric(
        domain="mining", metric="network_difficulty", subject_id=network_subject, user_id=user_id,
    )
    block_subsidy = await resolve_metric(
        domain="mining", metric="block_subsidy", subject_id=network_subject, user_id=user_id,
    )

    # ------------------------------------------------------------------
    # Operator state + scenario assumptions. These are immutable facts too.
    # ------------------------------------------------------------------
    available_capital = await _assumption(
        user_id=user_id, domain="capital", metric="available_capital",
        value=data.get("capital_usd"), unit="usd",
        methodology="Operator-stated capital available for this scenario",
    )
    available_power = await _assumption(
        user_id=user_id, domain="energy", metric="available_power_capacity",
        value=data.get("available_mw"), unit="mw",
        methodology="Operator-stated incremental power available for this scenario",
    )
    horizon = await _assumption(
        user_id=user_id, domain="capital", metric="horizon_months",
        value=data.get("horizon_months"), unit="months",
        methodology="Scenario horizon selected by operator",
    )
    delivered_power = await _assumption(
        user_id=user_id, domain="energy", metric="delivered_power_cost",
        value=data.get("electricity_usd_kwh"), unit="usd_kwh",
        methodology=(
            "Operator delivered electricity-cost assumption. This is distinct "
            "from a wholesale grid observation."
        ),
    )

    horizon_price_value = data.get("btc_price_at_horizon")
    if horizon_price_value is None:
        horizon_price_value = effective_btc
        horizon_method = "Default future-price scenario assumption: unchanged from current spot"
    else:
        horizon_method = "Operator BTC price-at-horizon scenario assumption"
    horizon_price = await _assumption(
        user_id=user_id, domain="market", metric="btc_horizon_price",
        value=horizon_price_value, unit="usd", subject_id="BTC",
        methodology=horizon_method,
    )

    pool_fee = await _assumption(
        user_id=user_id, domain="mining", metric="pool_fee_pct",
        value=data.get("pool_fee_pct"), unit="pct",
        methodology="Mining pool-fee scenario assumption",
    )
    mining_uptime = await _assumption(
        user_id=user_id, domain="mining", metric="uptime_pct",
        value=data.get("uptime_pct"), unit="pct",
        methodology="Mining uptime scenario assumption",
    )
    difficulty_growth = await _assumption(
        user_id=user_id, domain="mining", metric="difficulty_growth_pct_year",
        value=data.get("difficulty_growth_pct_year"), unit="pct_year",
        methodology="Future Bitcoin difficulty-growth scenario assumption",
    )

    # ------------------------------------------------------------------
    # Hardware market resolution. The selected fact becomes the engine input.
    # ------------------------------------------------------------------
    asic_model = str(data.get("asic_model") or asic.get("model") or "custom")
    hardware = await resolve_hardware_bundle(
        asic_model,
        user_id,
        explicit_price=data.get("hardware_cost_usd"),
        explicit_hashrate=data.get("hashrate_ths") if asic_model == "custom" else None,
        explicit_power_watts=data.get("power_watts") if asic_model == "custom" else None,
    )
    effective_asic = dict(asic)
    if hardware["price"].get("value") is not None:
        effective_asic["price_usd"] = float(hardware["price"]["value"])
    if hardware["hashrate"].get("value") is not None:
        effective_asic["hashrate_ths"] = float(hardware["hashrate"]["value"])
    if hardware["power"].get("value") is not None:
        effective_asic["power_watts"] = float(hardware["power"]["value"])

    # ------------------------------------------------------------------
    # GPU compute market + operator utilization/revenue assumptions.
    # ------------------------------------------------------------------
    gpu_model = str(data.get("gpu_model") or "")
    gpu_region = data.get("gpu_region")
    gpu_billing_model = data.get("gpu_billing_model")
    if gpu_model:
        compute = await resolve_compute_bundle(
            gpu_model,
            user_id,
            region=gpu_region,
            billing_model=gpu_billing_model,
            explicit_capex=data.get("gpu_capex_usd"),
            explicit_power_kw=data.get("gpu_power_kw"),
            explicit_cloud_rate=data.get("gpu_cloud_rental_usd_per_hr"),
        )
    else:
        compute = {
            "capex": await resolve_metric(domain="gpu", metric="gpu_capex", subject_id="__none__", user_id=user_id),
            "power": await resolve_metric(domain="gpu", metric="gpu_power", subject_id="__none__", user_id=user_id),
            "cloud_offer": await resolve_metric(domain="gpu", metric="compute_offer", subject_id="__none__", user_id=user_id),
        }

    cloud_rate = compute["cloud_offer"].get("value")
    achieved_rate_value = data.get("gpu_rental_usd_per_hr")
    if achieved_rate_value is None and cloud_rate is not None:
        achieved_rate_value = cloud_rate
        achieved_method = "Zero-margin default: achieved rate equals selected cloud offer"
    else:
        achieved_method = "Operator achieved GPU revenue-rate assumption"
    achieved_rate = await _assumption(
        user_id=user_id, domain="gpu", metric="achieved_compute_rate",
        value=achieved_rate_value, unit="usd_gpu_hr", subject_id=gpu_model or "gpu",
        methodology=achieved_method,
        extra={"gpu_model": gpu_model, "region": gpu_region, "billing_model": gpu_billing_model},
    )
    gpu_utilization = await _assumption(
        user_id=user_id, domain="gpu", metric="utilization_pct",
        value=data.get("gpu_utilization_pct"), unit="pct", subject_id=gpu_model or "gpu",
        methodology="GPU utilization scenario assumption",
    )
    gpu_uptime = await _assumption(
        user_id=user_id, domain="gpu", metric="uptime_pct",
        value=data.get("gpu_uptime_pct"), unit="pct", subject_id=gpu_model or "gpu",
        methodology="GPU uptime scenario assumption",
    )
    gpu_pue = await _assumption(
        user_id=user_id, domain="gpu", metric="pue",
        value=data.get("gpu_pue"), unit="ratio", subject_id=gpu_model or "gpu",
        methodology="Facility PUE scenario assumption",
    )
    gpu_units_cap = await _assumption(
        user_id=user_id, domain="gpu", metric="units_cap",
        value=data.get("gpu_units_cap"), unit="units", subject_id=gpu_model or "gpu",
        methodology="Operator maximum GPU unit count for this scenario",
    )

    # ------------------------------------------------------------------
    # Energy: market context is evidence, but NEVER silently substituted for
    # the operator's delivered electricity cost.
    # ------------------------------------------------------------------
    energy_region = data.get("energy_region")
    energy_market = await resolve_energy_market(user_id, region=energy_region)

    acquisition_value = data.get("energy_acquisition_usd_kwh")
    if acquisition_value is None:
        acquisition_value = data.get("electricity_usd_kwh")
        acquisition_method = "Defaults to operator delivered electricity-cost assumption"
    else:
        acquisition_method = "Operator energy acquisition-cost assumption"
    energy_acquisition = await _assumption(
        user_id=user_id, domain="energy", metric="energy_acquisition_cost",
        value=acquisition_value, unit="usd_kwh",
        methodology=acquisition_method,
    )
    energy_sell = await _assumption(
        user_id=user_id, domain="energy", metric="energy_sell_price",
        value=data.get("energy_sell_price_usd_kwh"), unit="usd_kwh",
        methodology="Operator sell / avoided-cost / PPA price assumption",
    )
    energy_utilization = await _assumption(
        user_id=user_id, domain="energy", metric="energy_utilization_pct",
        value=data.get("energy_utilization_pct"), unit="pct",
        methodology="Energy utilization scenario assumption",
    )
    storage_mwh = await _assumption(
        user_id=user_id, domain="energy", metric="storage_mwh",
        value=data.get("storage_mwh"), unit="mwh",
        methodology="Operator storage-capacity scenario input",
    )
    storage_capex = await _assumption(
        user_id=user_id, domain="energy", metric="storage_capex_usd_mwh",
        value=data.get("storage_capex_usd_per_mwh"), unit="usd_mwh",
        methodology="Storage capex scenario assumption",
    )
    storage_roundtrip = await _assumption(
        user_id=user_id, domain="energy", metric="storage_roundtrip_pct",
        value=data.get("storage_roundtrip_pct"), unit="pct",
        methodology="Storage round-trip efficiency scenario assumption",
    )
    cash_rate = await _assumption(
        user_id=user_id, domain="capital", metric="cash_interest_rate_pct_year",
        value=data.get("cash_interest_rate_pct_year"), unit="pct_year",
        methodology="Cash/reserve yield scenario assumption",
    )

    owned = await fleet_summary(user_id)

    # ------------------------------------------------------------------
    # Lane-level proof/quality. Context-only facts (e.g. wholesale energy price)
    # are shown separately so their absence cannot make a valid user-supplied
    # energy model look unavailable.
    # ------------------------------------------------------------------
    btc_lane = await lane_evidence(
        lane_key="btc", label="BTC Treasury",
        resolutions={"btc_spot": btc_res, "btc_horizon_price": horizon_price},
    )
    mining_lane = await lane_evidence(
        lane_key="mining", label="Bitcoin Mining",
        resolutions={
            "btc_spot": btc_res,
            "network_hashrate": network_hashrate,
            "network_difficulty": network_difficulty,
            "block_subsidy": block_subsidy,
            "asic_price": hardware["price"],
            "asic_hashrate": hardware["hashrate"],
            "asic_power": hardware["power"],
            "delivered_power_cost": delivered_power,
            "pool_fee_pct": pool_fee,
            "uptime_pct": mining_uptime,
            "difficulty_growth_pct_year": difficulty_growth,
        },
    )
    gpu_lane = await lane_evidence(
        lane_key="gpu", label="AI / GPU Compute",
        resolutions={
            "gpu_capex": compute["capex"],
            "gpu_power": compute["power"],
            "cloud_offer": compute["cloud_offer"],
            "achieved_compute_rate": achieved_rate,
            "delivered_power_cost": delivered_power,
            "utilization_pct": gpu_utilization,
            "uptime_pct": gpu_uptime,
            "pue": gpu_pue,
            "units_cap": gpu_units_cap,
        },
    )
    energy_lane_resolutions = {
        "delivered_power_cost": delivered_power,
        "energy_acquisition_cost": energy_acquisition,
        "energy_sell_price": energy_sell,
        "energy_utilization_pct": energy_utilization,
        "storage_mwh": storage_mwh,
        "storage_capex_usd_mwh": storage_capex,
        "storage_roundtrip_pct": storage_roundtrip,
    }
    if energy_market.get("fact_id"):
        energy_lane_resolutions["market_power_price_context"] = energy_market
    energy_lane = await lane_evidence(
        lane_key="energy", label="Energy / Storage",
        resolutions=energy_lane_resolutions,
    )

    lanes = {"btc": btc_lane, "mining": mining_lane, "gpu": gpu_lane, "energy": energy_lane}

    all_resolutions = {
        "available_capital": available_capital,
        "available_power": available_power,
        "horizon": horizon,
        "cash_rate": cash_rate,
        "energy_market_context": energy_market,
    }
    evidence_ids = []
    for lane in lanes.values():
        evidence_ids.extend(lane.get("facts_used", []))
    for res in all_resolutions.values():
        if res.get("fact_id"):
            evidence_ids.append(res["fact_id"])
    evidence_ids.extend(owned.get("evidence_ids", []))
    evidence_ids = list(dict.fromkeys(evidence_ids))

    total_observed = sum(l["state_counts"].get(E.OBSERVED_LIVE, 0) for l in lanes.values())
    total_assumed = sum(
        l["state_counts"].get(E.USER_ASSUMPTION, 0) + l["state_counts"].get(E.SIMULATION, 0)
        for l in lanes.values()
    )
    denominator = total_observed + total_assumed
    overall_observed_pct = round(total_observed / denominator * 100.0, 1) if denominator else 0.0
    overall_assumption_pct = round(total_assumed / denominator * 100.0, 1) if denominator else 0.0

    return {
        "engine": {
            "btc_price": effective_btc,
            "btc_price_provider": "user_input" if user_btc is not None else provenance.get("provider", "unknown"),
            "asic": effective_asic,
            "gpu_capex_usd": compute["capex"].get("value"),
            "gpu_power_kw": compute["power"].get("value"),
            "gpu_cloud_rental_usd_per_hr": compute["cloud_offer"].get("value"),
            "gpu_rental_usd_per_hr": achieved_rate.get("value"),
            "energy_acquisition_usd_kwh": energy_acquisition.get("value"),
            "energy_sell_price_usd_kwh": energy_sell.get("value"),
        },
        "owned": owned,
        "lanes": lanes,
        "evidence_ids": evidence_ids,
        "context": {
            "energy_market": energy_market,
            "operator_state": all_resolutions,
        },
        "quality": {
            "overall_observed_pct": overall_observed_pct,
            "overall_assumption_pct": overall_assumption_pct,
            "conflict_count": sum(l.get("conflict_count", 0) for l in lanes.values()),
            "stale_count": sum(len(l.get("facts_stale", [])) for l in lanes.values()),
            "missing_count": sum(len(l.get("facts_missing", [])) for l in lanes.values()),
        },
    }


def apply_evidence_to_result(result: Dict, prepared: Dict) -> Dict:
    """Attach lane evidence to a deterministic engine result without hiding it."""
    result["evidence"] = {
        "evidence_ids": prepared["evidence_ids"],
        "lanes": prepared["lanes"],
        "context": prepared["context"],
        "quality": prepared["quality"],
    }

    for key, block in prepared["lanes"].items():
        lane = result.get("lanes", {}).get(key)
        if not lane:
            continue
        lane["calculation_evidence"] = lane.get("evidence", {})
        lane["evidence"] = block
        lane["evidence_quality"] = {
            "label": block["quality_label"],
            "score": block["quality_score"],
            "observed_pct": block["observed_pct"],
            "assumption_pct": block["assumption_pct"],
            "conflicts": block["conflict_count"],
            "stale": len(block["facts_stale"]),
            "missing": len(block["facts_missing"]),
        }
        if block["quality_label"] == E.Q_UNAVAILABLE:
            lane["evidence_state"] = E.UNAVAILABLE
        elif block["state_counts"].get(E.SIMULATION, 0) and not block["state_counts"].get(E.OBSERVED_LIVE, 0):
            lane["evidence_state"] = E.SIMULATION
        elif block["quality_label"] == E.Q_COMPLETE:
            lane["evidence_state"] = E.OBSERVED_LIVE
        else:
            lane["evidence_state"] = E.USER_ASSUMPTION

    return result
