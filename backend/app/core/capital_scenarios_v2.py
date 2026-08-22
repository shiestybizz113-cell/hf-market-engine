"""Fleet-aware Capital V2 scenario matrix.

The original scenario helper predated the customer asset registry and therefore
recomputed stress cases as if the operator owned nothing. This V2 helper keeps
the same scenario definitions while passing the owned fleet through every
recalculation and applying the same integrity corrections as the base run.
"""

from typing import Dict, List, Optional

from app.core.capital_allocation import run_capital_allocation
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.mining import NetworkData


def _shift_network(net: Optional[Dict], difficulty: float) -> Optional[NetworkData]:
    if net is None:
        return None
    return NetworkData(
        provider=net.get("provider", "shifted"),
        source=net.get("source", "scenario"),
        observed_at=net.get("observed_at"),
        hashrate_ths=net.get("hashrate_ths", 0.0),
        difficulty=difficulty,
        block_subsidy=net.get("block_subsidy", 3.125),
        block_time_seconds=net.get("block_time_seconds", 600.0),
    )


def run_capital_scenarios_v2(*, base: Dict, vectors: List[Dict], owned: Optional[Dict]) -> List[Dict]:
    base_inputs = base["inputs"]
    base_observed = base["observed"]
    out: List[Dict] = []

    for vec in vectors:
        btc_shift = float(vec.get("btc_price_shift_pct", 0.0))
        elec_shift = float(vec.get("electricity_shift_pct", 0.0))
        diff_shift = float(vec.get("difficulty_shift_pct", 0.0))
        gpu_util_shift = float(vec.get("gpu_utilization_shift_pct", 0.0))
        gpu_rent_shift = float(vec.get("gpu_rental_shift_pct", 0.0))
        energy_sell_shift = float(vec.get("energy_sell_shift_pct", 0.0))

        btc_price = float(base_observed["btc_price"])
        horizon_price = float(base_inputs.get("btc_price_at_horizon") or btc_price)
        btc_price_at_horizon = horizon_price * (1.0 + btc_shift / 100.0)
        electricity = float(base_inputs["electricity_usd_kwh"]) * (1.0 + elec_shift / 100.0)

        network_dict = base_observed.get("network")
        difficulty = None
        if network_dict:
            difficulty = float(network_dict["difficulty"]) * (1.0 + diff_shift / 100.0)

        gpu_util = float(base_inputs.get("gpu_utilization_pct", 85.0)) * (1.0 + gpu_util_shift / 100.0)
        gpu_util = max(0.0, min(100.0, gpu_util))

        gpu_rental = base_inputs.get("gpu_rental_usd_per_hr")
        if gpu_rental is not None:
            gpu_rental = float(gpu_rental) * (1.0 + gpu_rent_shift / 100.0)

        energy_sell = base_inputs.get("energy_sell_price_usd_kwh")
        if energy_sell is not None:
            energy_sell = float(energy_sell) * (1.0 + energy_sell_shift / 100.0)

        res = run_capital_allocation(
            capital_usd=base_inputs["capital_usd"],
            available_mw=base_inputs["available_mw"],
            horizon_months=base_inputs["horizon_months"],
            electricity_usd_kwh=electricity,
            risk_profile=base_inputs["risk_profile"],
            network=None if difficulty is None else _shift_network(network_dict, difficulty),
            btc_price=btc_price,
            btc_price_provider=base_observed["btc_price_provider"],
            simulation=base_inputs.get("simulation", False),
            asic=base_inputs.get("asic", {}),
            pool_fee_pct=base_inputs.get("pool_fee_pct", 1.0),
            uptime_pct=base_inputs.get("uptime_pct", 95.0),
            btc_price_at_horizon=btc_price_at_horizon,
            difficulty_growth_pct_year=base_inputs.get("difficulty_growth_pct_year", 20.0),
            gpu_model=base_inputs.get("gpu_model", ""),
            gpu_capex_usd=base_inputs.get("gpu_capex_usd"),
            gpu_power_kw=base_inputs.get("gpu_power_kw"),
            gpu_cloud_rental_usd_per_hr=base_inputs.get("gpu_cloud_rental_usd_per_hr"),
            gpu_rental_usd_per_hr=gpu_rental,
            gpu_utilization_pct=gpu_util,
            gpu_uptime_pct=base_inputs.get("gpu_uptime_pct", 100.0),
            gpu_units_cap=base_inputs.get("gpu_units_cap", 256),
            gpu_pue=base_inputs.get("gpu_pue", 1.3),
            energy_acquisition_usd_kwh=base_inputs.get("energy_acquisition_usd_kwh"),
            energy_sell_price_usd_kwh=energy_sell,
            energy_utilization_pct=base_inputs.get("energy_utilization_pct", 100.0),
            storage_mwh=base_inputs.get("storage_mwh", 0.0),
            storage_capex_usd_per_mwh=base_inputs.get("storage_capex_usd_per_mwh", 0.0),
            storage_roundtrip_pct=base_inputs.get("storage_roundtrip_pct", 85.0),
            cash_interest_rate_pct_year=base_inputs.get("cash_interest_rate_pct_year", 4.0),
            owned=owned,
        )
        # Make scenario economics use the same corrected storage units/capital
        # basis as the base Capital run.
        apply_energy_storage_integrity(res)

        matrix: Dict[str, Dict] = {}
        for key, lane in res["lanes"].items():
            matrix[key] = {
                "available": lane["available"],
                "operating_profit_month": lane["operating_profit_month"],
                "revenue_month": lane["revenue_month"],
                "profit_per_mw": lane["profit_per_mw"],
                "horizon_value": lane["horizon_value"],
                "power_mw": lane.get("power_mw"),
                "integrity_version": lane.get("integrity_version"),
            }

        out.append({
            "label": vec["label"],
            "vector": {
                "btc_price_shift_pct": btc_shift,
                "electricity_shift_pct": elec_shift,
                "difficulty_shift_pct": diff_shift,
                "gpu_utilization_shift_pct": gpu_util_shift,
                "gpu_rental_shift_pct": gpu_rent_shift,
                "energy_sell_shift_pct": energy_sell_shift,
            },
            "btc_price": btc_price,
            "btc_price_at_horizon": btc_price_at_horizon,
            "difficulty": difficulty,
            "owned_fleet_accounted": True,
            "lanes": matrix,
        })

    return out
