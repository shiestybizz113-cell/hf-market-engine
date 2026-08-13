"""Post-engine integrity normalizers for Capital V2.

These functions repair legacy lane calculations while keeping the original
engine API stable. They are deterministic and applied to base + scenario runs.
"""

from typing import Dict

DAYS_PER_MONTH = 30.0
KWH_PER_MWH = 1000.0


def apply_energy_storage_integrity(result: Dict) -> Dict:
    """Correct energy/storage units, capital basis, and payback semantics.

    Legacy energy_lane had three issues:
    - MWh storage was multiplied directly by $/kWh (1,000x unit error),
    - storage payback in months was exposed as `simple_payback_days`,
    - owned storage was added to new storage capex.

    V2 treats storage_mwh in result.inputs as *new* proposed storage. Existing
    storage stays in the owned baseline and is never purchased again.
    """
    lanes = result.get("lanes", {})
    lane = lanes.get("energy")
    if not lane or not lane.get("available"):
        return result

    inputs = result.get("inputs", {})
    power_mw = float(lane.get("power_mw", 0.0) or 0.0)
    acquisition = inputs.get("energy_acquisition_usd_kwh")
    if acquisition is None:
        acquisition = inputs.get("electricity_usd_kwh", 0.0)
    acquisition = float(acquisition or 0.0)
    sell = float(inputs.get("energy_sell_price_usd_kwh") or 0.0)
    utilization = max(0.0, min(100.0, float(inputs.get("energy_utilization_pct", 100.0) or 0.0)))

    requested_storage_mwh = max(0.0, float(inputs.get("storage_mwh", 0.0) or 0.0))
    capex_per_mwh = max(0.0, float(inputs.get("storage_capex_usd_per_mwh", 0.0) or 0.0))
    roundtrip = max(0.0, min(100.0, float(inputs.get("storage_roundtrip_pct", 85.0) or 0.0))) / 100.0
    capital_usd = max(0.0, float(inputs.get("capital_usd", 0.0) or 0.0))
    horizon_months = max(0, int(inputs.get("horizon_months", 0) or 0))

    deployed_storage_mwh = requested_storage_mwh
    flags = [f for f in lane.get("risk_flags", []) if f not in {"negative_margin", "unprofitable"}]
    if capex_per_mwh > 0 and requested_storage_mwh * capex_per_mwh > capital_usd:
        deployed_storage_mwh = capital_usd / capex_per_mwh if capital_usd > 0 else 0.0
        flags.append("storage_capital_constraint_applied")
    elif requested_storage_mwh > 0 and capex_per_mwh <= 0:
        flags.append("storage_capex_missing")

    direct_kwh_day = power_mw * KWH_PER_MWH * 24.0 * (utilization / 100.0)
    direct_revenue_day = direct_kwh_day * sell
    direct_cost_day = direct_kwh_day * acquisition
    direct_profit_day = direct_revenue_day - direct_cost_day

    # One full storage cycle/day is still a stated scenario assumption. Charge
    # energy and round-trip losses are now accounted for with correct units.
    storage_charge_kwh_day = deployed_storage_mwh * KWH_PER_MWH
    storage_discharge_kwh_day = storage_charge_kwh_day * roundtrip
    storage_revenue_day = storage_discharge_kwh_day * sell
    storage_cost_day = storage_charge_kwh_day * acquisition
    storage_profit_day = storage_revenue_day - storage_cost_day

    revenue_day = direct_revenue_day + storage_revenue_day
    cost_day = direct_cost_day + storage_cost_day
    profit_day = direct_profit_day + storage_profit_day
    revenue_month = revenue_day * DAYS_PER_MONTH
    profit_month = profit_day * DAYS_PER_MONTH

    storage_capex = deployed_storage_mwh * capex_per_mwh
    simple_payback_days = storage_capex / profit_day if storage_capex > 0 and profit_day > 0 else None

    if profit_day <= 0:
        flags.append("negative_margin")
    flags.append("energy_v2_units_verified")

    owned_storage = float(
        result.get("owned", {}).get("summary", {}).get("storage_mwh", 0.0) or 0.0
    )

    lane.update({
        "capital_allocated": storage_capex,
        "capital_left": max(0.0, capital_usd - storage_capex),
        "revenue_day": revenue_day,
        "revenue_month": revenue_month,
        "operating_profit_day": profit_day,
        "operating_profit_month": profit_month,
        "capital_basis": storage_capex,
        "simple_payback_days": simple_payback_days,
        "revenue_per_mw": revenue_month / power_mw if power_mw > 0 else None,
        "profit_per_mw": profit_month / power_mw if power_mw > 0 else None,
        "horizon_value": profit_month * horizon_months - storage_capex,
        "risk_flags": list(dict.fromkeys(flags)),
        "per_unit": {
            "direct_kwh_day": direct_kwh_day,
            "direct_revenue_day": direct_revenue_day,
            "direct_cost_day": direct_cost_day,
            "direct_profit_day": direct_profit_day,
            "storage_charge_kwh_day": storage_charge_kwh_day,
            "storage_discharge_kwh_day": storage_discharge_kwh_day,
            "storage_revenue_day": storage_revenue_day,
            "storage_cost_day": storage_cost_day,
            "storage_profit_day": storage_profit_day,
            "roundtrip_efficiency": roundtrip,
        },
        "assumptions": {
            **lane.get("assumptions", {}),
            "storage_mwh_requested": requested_storage_mwh,
            "storage_mwh_deployed": deployed_storage_mwh,
            "owned_storage_mwh_excluded_from_new_capex": owned_storage,
            "storage_cycle_assumption": "one full cycle per day; hourly congestion/price shape not modeled",
        },
        "integrity_version": "energy-storage-v2",
    })
    return result
