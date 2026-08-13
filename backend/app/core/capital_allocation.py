"""
Capital Allocation Command Center engine.

Evaluates ONE canonical scenario across the four capital lanes on a single
normalized economic frame:

    btc     - financial capital: spot BTC treasury (no operating flow; horizon
              value is an explicit assumption)
    mining  - compute infrastructure: buy ASICs within capital AND power (MW)
    gpu     - compute infrastructure: buy GPUs within capital AND power (MW)
    energy  - energy infrastructure: acquire power at a cost basis, sell at an
              avoided-cost/PPA price; optional storage uplift (assumptions)

Every lane normalizes into the same metric schema (revenue_day/month,
operating_profit_day/month, capital_basis, simple_payback_days, power_mw,
revenue_per_mw, profit_per_mw, downside_profit, horizon_value) so the command
center, the scenario matrix and the optimizer all speak one language.

Evidence contract (same honesty rules as the rest of the system):
    OBSERVED_LIVE    - live provider value (BTC price, mining network)
    USER_ASSUMPTION  - operator-entered input (electricity, ASIC/GPU spec,
                       rental rates, energy prices, PUE, storage)
    SIMULATION       - entire run is demo/labeled simulation mode
    UNAVAILABLE      - required input missing; the lane is unavailable, it is
                       NEVER synthesized

Observed data and assumptions are kept in separate blocks on every lane and
in every receipt. No "ROI" figure is produced without a full capital basis;
only operating profit, simple payback and assumption-labeled horizon values.

The optimizer PROPOSES a split. It does not trade, spend or deploy anything.
"""

from typing import Dict, List, Optional

from app.core.mining import (
    NetworkData, compute_estimate, mine_vs_buy, network_data_dict,
)
from app.core.gpu import resolve_gpu, gpu_economics

DAYS_PER_MONTH = 30.0
KW_PER_MW = 1000.0

# Data states — the only four evidence states the command center may render.
OBSERVED_LIVE = "observed_live"
USER_ASSUMPTION = "user_assumption"
SIMULATION = "simulation"
UNAVAILABLE = "unavailable"

RISK_PROFILES = {
    "conservative": {"reserve_pct": 15.0, "treasury_floor_pct": 30.0},
    "balanced": {"reserve_pct": 10.0, "treasury_floor_pct": 15.0},
    "aggressive": {"reserve_pct": 5.0, "treasury_floor_pct": 5.0},
}

RANKING_BASIS = (
    "Ranked by monthly operating profit per MW consumed (profit_per_mw); "
    "BTC treasury has no operating flow and is ranked separately. Stated "
    "basis, not a total-return or risk-adjusted ranking."
)


# --------------------------------------------------------------------------- #
# Lanes
# --------------------------------------------------------------------------- #
def _empty_lane(key: str, label: str, *, available: bool, reason: Optional[str],
                capital: float, evidence_state: str, evidence: Dict,
                risk_flags: Optional[List[str]] = None) -> Dict:
    return {
        "key": key,
        "label": label,
        "available": available,
        "reason": reason,
        "capital_allocated": capital if available else 0.0,
        "capital_left": 0.0 if available else capital,
        "power_mw": 0.0,
        "units": None,
        "revenue_day": 0.0,
        "revenue_month": 0.0,
        "operating_profit_day": 0.0,
        "operating_profit_month": 0.0,
        "capital_basis": 0.0,
        "simple_payback_days": None,
        "revenue_per_mw": None,
        "profit_per_mw": None,
        "downside_profit": None,
        "horizon_value": None,
        "evidence_state": evidence_state,
        "evidence": evidence,
        "risk_flags": risk_flags or [],
        "per_unit": {},
        "assumptions": evidence.get("assumptions", {}),
    }


def btc_lane(*, capital_usd: float, btc_price: float,
             btc_price_at_horizon: float, evidence_state: str,
             provider: str) -> Dict:
    """Financial capital: spot BTC treasury."""
    if btc_price <= 0:
        lane = _empty_lane(
            "btc", "Buy BTC (spot treasury)", available=False,
            reason="BTC price unavailable", capital=capital_usd,
            evidence_state=evidence_state,
            evidence={"observed": {}, "assumptions": {}},
        )
        lane["risk_flags"] = ["btc_price_unavailable"]
        return lane
    btc_exposure = capital_usd / btc_price
    horizon_value = btc_exposure * btc_price_at_horizon
    lane = {
        "key": "btc",
        "label": "Buy BTC (spot treasury)",
        "available": True,
        "reason": None,
        "capital_allocated": capital_usd,
        "capital_left": 0.0,
        "power_mw": 0.0,
        "units": btc_exposure,
        "revenue_day": 0.0,
        "revenue_month": 0.0,
        "operating_profit_day": 0.0,
        "operating_profit_month": 0.0,
        "capital_basis": capital_usd,
        "simple_payback_days": None,
        "revenue_per_mw": None,
        "profit_per_mw": None,
        "downside_profit": 0.0,
        "downside_horizon_value": horizon_value * 0.75,
        "horizon_value": horizon_value,
        "evidence_state": evidence_state,
        "evidence": {
            "observed": {"btc_price": btc_price, "btc_price_provider": provider},
            "assumptions": {
                "horizon_months": None,
                "btc_price_at_horizon": btc_price_at_horizon,
                "note": "Horizon value assumes BTC is held and the horizon price assumption is reached.",
            },
        },
        "risk_flags": ["full_btc_exposure", "no_operating_flow"],
        "per_unit": {},
        "assumptions": {"btc_price_at_horizon": btc_price_at_horizon},
    }
    return lane


def mining_lane(*, capital_usd: float, available_mw: float, asic: Dict,
                network: NetworkData, btc_price: float,
                electricity_usd_kwh: float, pool_fee_pct: float,
                uptime_pct: float, horizon_months: int,
                btc_price_at_horizon: float, difficulty_growth_pct_year: float,
                evidence_state: str, provider: str,
                setup_cost_usd_per_unit: float = 0.0,
                hosting_cost_usd_per_unit_month: float = 0.0,
                maintenance_cost_usd_per_unit_month: float = 0.0,
                hardware_resale_value_usd_per_unit: float = 0.0) -> Dict:
    """Compute infrastructure: mine within capital AND power constraints."""
    units_by_capital = (
        int(capital_usd // asic["price_usd"]) if asic["price_usd"] > 0 else 0
    )
    units_by_power = 0
    if available_mw > 0 and asic["power_watts"] > 0:
        units_by_power = int((available_mw * KW_PER_MW) // (asic["power_watts"] / 1000.0))
    units = min(units_by_capital, units_by_power) if available_mw > 0 else units_by_capital

    evidence = {
        "observed": {"btc_price": btc_price, "btc_price_provider": provider,
                     "network": network_data_dict(network)},
        "assumptions": {
            "electricity_usd_kwh": electricity_usd_kwh,
            "pool_fee_pct": pool_fee_pct,
            "uptime_pct": uptime_pct,
            "asic_model": asic.get("model"),
            "asic_price_usd": asic["price_usd"],
            "difficulty_growth_pct_year": difficulty_growth_pct_year,
            "horizon_months": horizon_months,
            "btc_price_at_horizon": btc_price_at_horizon,
            "setup_cost_usd_per_unit": setup_cost_usd_per_unit,
            "hosting_cost_usd_per_unit_month": hosting_cost_usd_per_unit_month,
            "maintenance_cost_usd_per_unit_month": maintenance_cost_usd_per_unit_month,
            "hardware_resale_value_usd_per_unit": hardware_resale_value_usd_per_unit,
        },
    }

    if units <= 0:
        lane = _empty_lane(
            "mining", "Bitcoin mining (ASICs)", available=False,
            reason=(
                "Capital below one ASIC's cost, or power budget below one unit's draw."
                if available_mw >= 0 else "Power budget unavailable"
            ),
            capital=capital_usd, evidence_state=evidence_state, evidence=evidence,
            risk_flags=["insufficient_capital_or_power"],
        )
        lane["assumptions"] = evidence["assumptions"]
        return lane

    est = compute_estimate(
        hashrate_ths=asic["hashrate_ths"],
        power_watts=asic["power_watts"],
        electricity_usd_kwh=electricity_usd_kwh,
        pool_fee_pct=pool_fee_pct,
        uptime_pct=uptime_pct,
        btc_price=btc_price,
        hardware_cost_usd=asic["price_usd"],
        network=network,
    )
    # Horizon value uses the same reconciled capital accounting as mine-vs-buy:
    # equipment + working capital + opex funding + residual. All capital in
    # this lane buys ASICs first; working capital funds power over the horizon.
    mvb = mine_vs_buy(
        capital_usd=capital_usd,
        asic=asic,
        btc_price=btc_price,
        electricity_usd_kwh=electricity_usd_kwh,
        pool_fee_pct=pool_fee_pct,
        uptime_pct=uptime_pct,
        horizon_days=int(horizon_months * DAYS_PER_MONTH),
        difficulty_growth_pct_year=difficulty_growth_pct_year,
        btc_price_at_horizon=btc_price_at_horizon,
        network=network,
        setup_cost_usd_per_unit=setup_cost_usd_per_unit,
        hosting_cost_usd_per_unit_month=hosting_cost_usd_per_unit_month,
        maintenance_cost_usd_per_unit_month=maintenance_cost_usd_per_unit_month,
        hardware_resale_value_usd_per_unit=hardware_resale_value_usd_per_unit,
    )
    mvb_mining = mvb.get("mining_path", {})
    power_mw = units * asic["power_watts"] / (KW_PER_MW * 1000.0)
    revenue_month = est["revenue_day"] * units * DAYS_PER_MONTH
    profit_month = est["operating_profit_day"] * units * DAYS_PER_MONTH
    flags = ["assumption_sensitive"]
    if est["operating_profit_day"] <= 0:
        flags.append("unprofitable")
    if est.get("break_even_electricity_usd_kwh") is not None and \
            electricity_usd_kwh >= est["break_even_electricity_usd_kwh"]:
        flags.append("below_break_even_electricity")
    if est.get("simple_payback_days") is not None and est["simple_payback_days"] > 730:
        flags.append("slow_payback")

    lane = {
        "key": "mining",
        "label": f"Bitcoin mining ({units}x {asic.get('model', asic.get('name', 'ASIC'))})",
        "available": True,
        "reason": None,
        "capital_allocated": units * asic["price_usd"],
        "capital_left": max(0.0, capital_usd - units * asic["price_usd"]),
        "power_mw": power_mw,
        "units": units,
        "revenue_day": est["revenue_day"] * units,
        "revenue_month": revenue_month,
        "operating_profit_day": est["operating_profit_day"] * units,
        "operating_profit_month": profit_month,
        "capital_basis": units * asic["price_usd"],
        "simple_payback_days": est["simple_payback_days"],
        "revenue_per_mw": revenue_month / power_mw if power_mw > 0 else None,
        "profit_per_mw": profit_month / power_mw if power_mw > 0 else None,
        "downside_profit": None,  # filled by the scenario engine under stress
        "horizon_value": mvb_mining.get("value_at_horizon"),
        "evidence_state": evidence_state,
        "evidence": evidence,
        "risk_flags": flags,
        "per_unit": est,
        "assumptions": evidence["assumptions"],
    }
    return lane


def gpu_lane(*, capital_usd: float, available_mw: float,
             electricity_usd_kwh: float, gpu_model: str,
             gpu_capex_usd: Optional[float], gpu_power_kw: Optional[float],
             gpu_cloud_rental_usd_per_hr: Optional[float],
             gpu_rental_usd_per_hr: Optional[float],
             gpu_utilization_pct: float, gpu_uptime_pct: float,
             gpu_units_cap: int, gpu_pue: float, horizon_months: int,
             evidence_state: str) -> Dict:
    """Compute infrastructure: build GPUs within capital AND power."""
    gpu = resolve_gpu(
        gpu_model or None, gpu_capex_usd, gpu_power_kw, gpu_cloud_rental_usd_per_hr,
    )
    active = gpu.get("present", False)
    achieved_rate = gpu_rental_usd_per_hr
    cloud_rate = gpu.get("cloud_rental_usd_hr")
    if active and achieved_rate is None:
        achieved_rate = cloud_rate  # zero-margin conservative default
    gpu_assumptions = {
        "gpu_model": gpu.get("model"),
        "gpu_capex_usd": gpu.get("capex_usd"),
        "gpu_power_kw": gpu.get("power_kw"),
        "gpu_achieved_rental_usd_hr": achieved_rate,
        "gpu_cloud_rental_usd_hr": cloud_rate,
        "gpu_utilization_pct": gpu_utilization_pct,
        "gpu_uptime_pct": gpu_uptime_pct,
        "gpu_units_cap": gpu_units_cap,
        "gpu_pue": gpu_pue,
        "horizon_months": horizon_months,
    }
    evidence = {
        "observed": {},
        "assumptions": gpu_assumptions,
        "note": "All GPU economics are operator assumptions; no live GPU spot provider is wired.",
    }

    if not active:
        lane = _empty_lane(
            "gpu", "AI / GPU compute (build)", available=False,
            reason="No GPU model selected (set gpu_model or gpu_capex_usd + gpu_power_kw).",
            capital=capital_usd, evidence_state=evidence_state, evidence=evidence,
            risk_flags=["pending_inputs"],
        )
        lane["assumptions"] = gpu_assumptions
        return lane

    units_by_capital = (
        int(capital_usd // gpu["capex_usd"]) if gpu["capex_usd"] > 0 else 0
    )
    units_by_power = 0
    if available_mw > 0 and gpu["power_kw"] > 0:
        units_by_power = int((available_mw * KW_PER_MW) // gpu["power_kw"])
    units = min(gpu_units_cap, units_by_capital)
    if available_mw > 0:
        units = min(units, units_by_power)

    if units <= 0:
        lane = _empty_lane(
            "gpu", "AI / GPU compute (build)", available=False,
            reason=(
                "Capital below one GPU's cost, or power budget below one GPU's draw."
                if available_mw >= 0 else "Power budget unavailable"
            ),
            capital=capital_usd, evidence_state=evidence_state, evidence=evidence,
            risk_flags=["insufficient_capital_or_power"],
        )
        lane["assumptions"] = gpu_assumptions
        return lane

    gest = gpu_economics(
        gpu=gpu,
        achieved_rental_usd_hr=achieved_rate,
        cloud_rental_usd_hr=cloud_rate,
        utilization_pct=gpu_utilization_pct,
        uptime_pct=gpu_uptime_pct,
        electricity_usd_kwh=electricity_usd_kwh,
        pue=gpu_pue,
    )
    power_mw = units * gpu["power_kw"] / KW_PER_MW
    revenue_month = gest["revenue_day"] * units * DAYS_PER_MONTH
    profit_month = gest["build_profit_day"] * units * DAYS_PER_MONTH
    capex_deployed = units * gpu["capex_usd"]
    flags = ["gpu_economics_assumed"]
    if gest["build_profit_day"] <= 0:
        flags.append("unprofitable")
    if gest.get("build_payback_days") is not None and gest["build_payback_days"] > 730:
        flags.append("slow_payback")

    lane = {
        "key": "gpu",
        "label": f"AI / GPU compute ({units}x {gpu['model']})",
        "available": True,
        "reason": None,
        "capital_allocated": capex_deployed,
        "capital_left": max(0.0, capital_usd - capex_deployed),
        "power_mw": power_mw,
        "units": units,
        "revenue_day": gest["revenue_day"] * units,
        "revenue_month": revenue_month,
        "operating_profit_day": gest["build_profit_day"] * units,
        "operating_profit_month": profit_month,
        "capital_basis": capex_deployed,
        "simple_payback_days": gest["build_payback_days"],
        "revenue_per_mw": revenue_month / power_mw if power_mw > 0 else None,
        "profit_per_mw": profit_month / power_mw if power_mw > 0 else None,
        "downside_profit": None,
        "horizon_value": profit_month * horizon_months - capex_deployed,
        "evidence_state": evidence_state,
        "evidence": evidence,
        "risk_flags": flags,
        "per_unit": gest,
        "assumptions": gpu_assumptions,
    }
    return lane


def energy_lane(*, available_mw: float, electricity_usd_kwh: float,
                energy_acquisition_usd_kwh: Optional[float],
                energy_sell_price_usd_kwh: Optional[float],
                energy_utilization_pct: float,
                storage_mwh: float, storage_capex_usd_per_mwh: float,
                storage_roundtrip_pct: float, horizon_months: int,
                evidence_state: str) -> Dict:
    """Energy infrastructure: acquire power, sell at avoided-cost/PPA price.

    All energy inputs are operator assumptions (no live energy provider is
    wired). Storage, when supplied, adds daily arbitrage uplift (cycles per
    day is a fixed conservative assumption) plus capex basis.
    """
    acquisition = (
        energy_acquisition_usd_kwh if energy_acquisition_usd_kwh is not None
        else electricity_usd_kwh
    )
    sell_price = energy_sell_price_usd_kwh or 0.0
    assumptions = {
        "energy_acquisition_usd_kwh": acquisition,
        "energy_sell_price_usd_kwh": sell_price,
        "energy_utilization_pct": energy_utilization_pct,
        "storage_mwh": storage_mwh,
        "storage_capex_usd_per_mwh": storage_capex_usd_per_mwh,
        "storage_roundtrip_pct": storage_roundtrip_pct,
        "horizon_months": horizon_months,
    }
    evidence = {
        "observed": {},
        "assumptions": assumptions,
        "note": "Energy economics are operator assumptions; no live power price provider is wired.",
    }

    if available_mw <= 0:
        lane = _empty_lane(
            "energy", "Energy / storage", available=False,
            reason="No power budget (available_mw = 0).",
            capital=0.0, evidence_state=evidence_state, evidence=evidence,
        )
        lane["assumptions"] = assumptions
        return lane
    if sell_price <= 0:
        lane = _empty_lane(
            "energy", "Energy / storage", available=False,
            reason="Set an energy sell / avoided-cost price (energy_sell_price_usd_kwh).",
            capital=0.0, evidence_state=evidence_state, evidence=evidence,
            risk_flags=["pending_inputs"],
        )
        lane["assumptions"] = assumptions
        return lane

    util = max(0.0, min(100.0, energy_utilization_pct))
    kwh_day = available_mw * KW_PER_MW * 24.0 * (util / 100.0)
    revenue_day = kwh_day * sell_price
    cost_day = kwh_day * acquisition
    profit_day = revenue_day - cost_day
    revenue_month = revenue_day * DAYS_PER_MONTH
    profit_month = profit_day * DAYS_PER_MONTH

    storage_capex = storage_mwh * storage_capex_usd_per_mwh if storage_mwh > 0 else 0.0
    storage_uplift_day = 0.0
    if storage_mwh > 0 and sell_price > acquisition:
        # Conservative fixed-cycle arbitrage assumption: one full cycle per day.
        roundtrip = max(0.0, min(100.0, storage_roundtrip_pct)) / 100.0
        storage_uplift_day = storage_mwh * roundtrip * (sell_price - acquisition)
    profit_month_total = profit_month + storage_uplift_day * DAYS_PER_MONTH
    payback = (
        storage_capex / profit_month_total if storage_capex > 0 and profit_month_total > 0
        else None
    )

    flags = ["energy_economics_assumed"]
    if profit_month_total <= 0:
        flags.append("negative_margin")

    lane = {
        "key": "energy",
        "label": "Energy / storage (power arbitrage)",
        "available": True,
        "reason": None,
        "capital_allocated": storage_capex,
        "capital_left": storage_capex,
        "power_mw": available_mw,
        "units": None,
        "revenue_day": revenue_day,
        "revenue_month": revenue_month + storage_uplift_day * DAYS_PER_MONTH,
        "operating_profit_day": profit_day + storage_uplift_day,
        "operating_profit_month": profit_month_total,
        "capital_basis": storage_capex,
        "simple_payback_days": payback,
        "revenue_per_mw": (revenue_month + storage_uplift_day * DAYS_PER_MONTH) / available_mw,
        "profit_per_mw": profit_month_total / available_mw,
        "downside_profit": None,
        "horizon_value": profit_month_total * horizon_months - storage_capex,
        "evidence_state": evidence_state,
        "evidence": evidence,
        "risk_flags": flags,
        "per_unit": {"revenue_day": revenue_day, "cost_day": cost_day,
                     "profit_day": profit_day, "storage_uplift_day": storage_uplift_day,
                     "kwh_day": kwh_day},
        "assumptions": assumptions,
    }
    return lane


# --------------------------------------------------------------------------- #
# Canonical run
# --------------------------------------------------------------------------- #
def run_capital_allocation(
    *,
    capital_usd: float,
    available_mw: float,
    horizon_months: int,
    electricity_usd_kwh: float,
    risk_profile: str,
    network: Optional[NetworkData],
    btc_price: float,
    btc_price_provider: str,
    simulation: bool,
    asic: Dict,
    pool_fee_pct: float,
    uptime_pct: float,
    btc_price_at_horizon: Optional[float],
    difficulty_growth_pct_year: float,
    gpu_model: str,
    gpu_capex_usd: Optional[float],
    gpu_power_kw: Optional[float],
    gpu_cloud_rental_usd_per_hr: Optional[float],
    gpu_rental_usd_per_hr: Optional[float],
    gpu_utilization_pct: float,
    gpu_uptime_pct: float,
    gpu_units_cap: int,
    gpu_pue: float,
    energy_acquisition_usd_kwh: Optional[float],
    energy_sell_price_usd_kwh: Optional[float],
    energy_utilization_pct: float,
    storage_mwh: float,
    storage_capex_usd_per_mwh: float,
    storage_roundtrip_pct: float,
    cash_interest_rate_pct_year: float,
) -> Dict:
    """Evaluate one canonical scenario across all four lanes.

    ``simulation`` forces evidence_state=SIMULATION on every lane; otherwise
    observed-live lanes use OBSERVED_LIVE and assumption lanes use
    USER_ASSUMPTION.
    """
    if simulation:
        state = SIMULATION
    else:
        state = OBSERVED_LIVE
    assumption_state = SIMULATION if simulation else USER_ASSUMPTION

    horizon_price = btc_price_at_horizon or btc_price

    lanes: Dict[str, Dict] = {
        "btc": btc_lane(
            capital_usd=capital_usd, btc_price=btc_price,
            btc_price_at_horizon=horizon_price,
            evidence_state=state, provider=btc_price_provider,
        ),
    }

    if network is not None:
        lanes["mining"] = mining_lane(
            capital_usd=capital_usd, available_mw=available_mw, asic=asic,
            network=network, btc_price=btc_price,
            electricity_usd_kwh=electricity_usd_kwh,
            pool_fee_pct=pool_fee_pct, uptime_pct=uptime_pct,
            horizon_months=horizon_months, btc_price_at_horizon=horizon_price,
            difficulty_growth_pct_year=difficulty_growth_pct_year,
            evidence_state=state, provider=btc_price_provider,
        )
    else:
        lanes["mining"] = _empty_lane(
            "mining", "Bitcoin mining (ASICs)", available=False,
            reason="Network data unavailable — no mining claim made.",
            capital=capital_usd, evidence_state=UNAVAILABLE,
            evidence={"observed": {}, "assumptions": {}},
        )

    lanes["gpu"] = gpu_lane(
        capital_usd=capital_usd, available_mw=available_mw,
        electricity_usd_kwh=electricity_usd_kwh,
        gpu_model=gpu_model, gpu_capex_usd=gpu_capex_usd,
        gpu_power_kw=gpu_power_kw,
        gpu_cloud_rental_usd_per_hr=gpu_cloud_rental_usd_per_hr,
        gpu_rental_usd_per_hr=gpu_rental_usd_per_hr,
        gpu_utilization_pct=gpu_utilization_pct, gpu_uptime_pct=gpu_uptime_pct,
        gpu_units_cap=gpu_units_cap, gpu_pue=gpu_pue,
        horizon_months=horizon_months, evidence_state=assumption_state,
    )

    lanes["energy"] = energy_lane(
        available_mw=available_mw, electricity_usd_kwh=electricity_usd_kwh,
        energy_acquisition_usd_kwh=energy_acquisition_usd_kwh,
        energy_sell_price_usd_kwh=energy_sell_price_usd_kwh,
        energy_utilization_pct=energy_utilization_pct,
        storage_mwh=storage_mwh,
        storage_capex_usd_per_mwh=storage_capex_usd_per_mwh,
        storage_roundtrip_pct=storage_roundtrip_pct,
        horizon_months=horizon_months, evidence_state=assumption_state,
    )

    ranking = _rank_lanes(lanes)
    recommendation = propose_allocation(
        capital_usd=capital_usd, lanes=lanes, risk_profile=risk_profile,
    )

    return {
        "inputs": {
            "capital_usd": capital_usd,
            "available_mw": available_mw,
            "horizon_months": horizon_months,
            "electricity_usd_kwh": electricity_usd_kwh,
            "risk_profile": risk_profile,
            "cash_interest_rate_pct_year": cash_interest_rate_pct_year,
            "simulation": simulation,
            "asic": asic,
            "pool_fee_pct": pool_fee_pct,
            "uptime_pct": uptime_pct,
            "btc_price_at_horizon": btc_price_at_horizon,
            "difficulty_growth_pct_year": difficulty_growth_pct_year,
            "gpu_model": gpu_model,
            "gpu_capex_usd": gpu_capex_usd,
            "gpu_power_kw": gpu_power_kw,
            "gpu_cloud_rental_usd_per_hr": gpu_cloud_rental_usd_per_hr,
            "gpu_rental_usd_per_hr": gpu_rental_usd_per_hr,
            "gpu_utilization_pct": gpu_utilization_pct,
            "gpu_uptime_pct": gpu_uptime_pct,
            "gpu_units_cap": gpu_units_cap,
            "gpu_pue": gpu_pue,
            "energy_acquisition_usd_kwh": energy_acquisition_usd_kwh,
            "energy_sell_price_usd_kwh": energy_sell_price_usd_kwh,
            "energy_utilization_pct": energy_utilization_pct,
            "storage_mwh": storage_mwh,
            "storage_capex_usd_per_mwh": storage_capex_usd_per_mwh,
            "storage_roundtrip_pct": storage_roundtrip_pct,
        },
        "observed": {
            "btc_price": btc_price,
            "btc_price_provider": btc_price_provider,
            "btc_price_observed": not simulation,
            "network": network_data_dict(network) if network else None,
        },
        "lanes": lanes,
        "ranking": ranking,
        "ranking_basis": RANKING_BASIS,
        "recommendation": recommendation,
    }


def _rank_lanes(lanes: Dict[str, Dict]) -> List[str]:
    """Available operating lanes by profit_per_mw; BTC ranked separately."""
    def sort_key(item):
        key, lane = item
        if not lane.get("available"):
            return (2, 0.0)  # unavailable last
        ppm = lane.get("profit_per_mw")
        if key == "btc":
            return (1, float("-inf"))  # no operating flow, ranked above unavailable
        if ppm is None:
            return (1, float("-inf"))
        return (0, -float(ppm))  # operating lanes first, best ppm first
    return [k for k, _ in sorted(lanes.items(), key=sort_key)]


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
SCENARIO_DEFS: Dict[str, Dict] = {
    "base": {
        "label": "Base",
        "btc_price_shift_pct": 0.0,
        "electricity_shift_pct": 0.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "btc_m25": {
        "label": "BTC -25%",
        "btc_price_shift_pct": -25.0,
        "electricity_shift_pct": 0.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "btc_p25": {
        "label": "BTC +25%",
        "btc_price_shift_pct": 25.0,
        "electricity_shift_pct": 0.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "power_p30": {
        "label": "Power +30%",
        "btc_price_shift_pct": 0.0,
        "electricity_shift_pct": 30.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "power_m20": {
        "label": "Power -20%",
        "btc_price_shift_pct": 0.0,
        "electricity_shift_pct": -20.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "difficulty_p20": {
        "label": "Difficulty +20%",
        "btc_price_shift_pct": 0.0,
        "electricity_shift_pct": 0.0,
        "difficulty_shift_pct": 20.0,
        "gpu_utilization_shift_pct": 0.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "gpu_util_m20": {
        "label": "GPU utilization -20%",
        "btc_price_shift_pct": 0.0,
        "electricity_shift_pct": 0.0,
        "difficulty_shift_pct": 0.0,
        "gpu_utilization_shift_pct": -20.0,
        "gpu_rental_shift_pct": 0.0,
        "energy_sell_shift_pct": 0.0,
    },
    "bull": {
        "label": "Bull",
        "btc_price_shift_pct": 25.0,
        "electricity_shift_pct": -10.0,
        "difficulty_shift_pct": 10.0,
        "gpu_utilization_shift_pct": 10.0,
        "gpu_rental_shift_pct": 15.0,
        "energy_sell_shift_pct": 10.0,
    },
    "stress": {
        "label": "Stress",
        "btc_price_shift_pct": -25.0,
        "electricity_shift_pct": 30.0,
        "difficulty_shift_pct": 20.0,
        "gpu_utilization_shift_pct": -20.0,
        "gpu_rental_shift_pct": -10.0,
        "energy_sell_shift_pct": -10.0,
    },
}


def run_capital_scenarios(
    *,
    base: Dict,
    vectors: List[Dict],
) -> List[Dict]:
    """Re-run the canonical engine under each scenario vector.

    ``base`` is the output of run_capital_allocation (its inputs are cloned and
    shifted). Returns a list of {label, vector, lanes} where each lane is the
    normalized metric dict.
    """
    base_inputs = base["inputs"]
    base_observed = base["observed"]
    out: List[Dict] = []
    for vec in vectors:
        label = vec["label"]
        btc_shift = vec.get("btc_price_shift_pct", 0.0)
        elec_shift = vec.get("electricity_shift_pct", 0.0)
        diff_shift = vec.get("difficulty_shift_pct", 0.0)
        gpu_util_shift = vec.get("gpu_utilization_shift_pct", 0.0)
        gpu_rent_shift = vec.get("gpu_rental_shift_pct", 0.0)
        energy_sell_shift = vec.get("energy_sell_shift_pct", 0.0)

        btc = base_observed["btc_price"]
        # Spot stays at today's observed price (the price you deploy at); the
        # horizon assumption moves with the scenario so treasury and mining
        # horizon values actually respond to a BTC shift.
        btc_price = btc
        horizon_price = base_inputs.get("btc_price_at_horizon") or btc
        btc_price_at_horizon = horizon_price * (1 + btc_shift / 100.0)
        electricity = base_inputs["electricity_usd_kwh"] * (1 + elec_shift / 100.0)
        difficulty = (
            base_observed["network"]["difficulty"] * (1 + diff_shift / 100.0)
            if base_observed.get("network") else None
        )
        gpu_util = base_inputs.get("gpu_utilization_pct", 85.0) * (1 + gpu_util_shift / 100.0)
        gpu_rental = None
        if base_inputs.get("gpu_rental_usd_per_hr") is not None:
            gpu_rental = base_inputs["gpu_rental_usd_per_hr"] * (1 + gpu_rent_shift / 100.0)
        energy_sell = None
        if base_inputs.get("energy_sell_price_usd_kwh") is not None:
            energy_sell = base_inputs["energy_sell_price_usd_kwh"] * (1 + energy_sell_shift / 100.0)

        res = run_capital_allocation(
            capital_usd=base_inputs["capital_usd"],
            available_mw=base_inputs["available_mw"],
            horizon_months=base_inputs["horizon_months"],
            electricity_usd_kwh=electricity,
            risk_profile=base_inputs["risk_profile"],
            network=None if difficulty is None else _shift_network(
                base_observed.get("network"), difficulty,
            ),
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
        )
        # Downside case: compute each lane's profit_month under this vector.
        # For BTC the downside is expressed via horizon value instead.
        matrix = {}
        for key, lane in res["lanes"].items():
            matrix[key] = {
                "available": lane["available"],
                "operating_profit_month": lane["operating_profit_month"],
                "revenue_month": lane["revenue_month"],
                "profit_per_mw": lane["profit_per_mw"],
                "horizon_value": lane["horizon_value"],
            }
        out.append({
            "label": label,
            "vector": {
                "btc_price_shift_pct": btc_shift,
                "electricity_shift_pct": elec_shift,
                "difficulty_shift_pct": diff_shift,
                "gpu_utilization_shift_pct": gpu_util_shift,
                "gpu_rental_shift_pct": gpu_rent_shift,
                "energy_sell_shift_pct": energy_sell_shift,
            },
            "btc_price": btc_price,
            "difficulty": difficulty,
            "lanes": matrix,
        })
    return out


def _shift_network(net: Optional[Dict], difficulty: float) -> Optional[NetworkData]:
    if net is None:
        return None
    return NetworkData(
        provider=net.get("provider", "shifted"),
        source=net.get("source", "scenario"),
        observed_at=None,
        hashrate_ths=net.get("hashrate_ths", 0.0),
        difficulty=difficulty,
        block_subsidy=net.get("block_subsidy", 3.125),
        block_time_seconds=net.get("block_time_seconds", 600.0),
    )


# --------------------------------------------------------------------------- #
# Optimizer (proposes only — never executes)
# --------------------------------------------------------------------------- #
def propose_allocation(*, capital_usd: float, lanes: Dict[str, Dict],
                       risk_profile: str) -> Dict:
    """Heuristic proposal of a capital split across the four buckets.

    PROPOSAL ONLY. Returns pct + per-lane USD. Does not trade, spend or deploy.
    The AI council explains why, and a human approves before anything executes.
    """
    profile = RISK_PROFILES.get(risk_profile, RISK_PROFILES["balanced"])
    reserve_pct = profile["reserve_pct"]
    treasury_floor_pct = profile["treasury_floor_pct"]

    # Score available operating lanes by profit_per_mw (absolute monthly flow
    # for zero-MW lanes). Treasury gets its floor; reserve gets its floor; the
    # remainder is split across operating lanes proportional to score.
    scores: Dict[str, float] = {}
    for key in ("gpu", "mining", "energy"):
        lane = lanes.get(key)
        if lane and lane.get("available"):
            ppm = lane.get("profit_per_mw")
            score = ppm if ppm is not None else lane.get("operating_profit_month", 0.0)
            if score and score > 0:
                scores[key] = score

    remaining = max(0.0, 100.0 - reserve_pct - treasury_floor_pct)
    if scores:
        total = sum(scores.values())
        weight = {k: scores[k] / total * remaining for k in scores}
    else:
        # No operating lane available: capital stays in treasury + reserve.
        weight = {}

    gpu_pct = weight.get("gpu", 0.0)
    mining_pct = weight.get("mining", 0.0)
    energy_pct = weight.get("energy", 0.0)
    # When an operating lane cannot absorb its weight (insufficient capital),
    # leave the remainder in the treasury.
    split_usd = {k: capital_usd * v / 100.0 for k, v in weight.items()}
    deployed = sum(split_usd.values())
    if deployed > capital_usd:
        scale = capital_usd / deployed if deployed > 0 else 0.0
        split_usd = {k: v * scale for k, v in split_usd.items()}
        gpu_pct *= scale
        mining_pct *= scale
        energy_pct *= scale

    treasury_pct = 100.0 - reserve_pct - gpu_pct - mining_pct - energy_pct
    treasury_pct = max(0.0, treasury_pct)

    proposed = {
        "gpu_compute_pct": round(gpu_pct, 1),
        "bitcoin_mining_pct": round(mining_pct, 1),
        "btc_treasury_pct": round(treasury_pct, 1),
        "reserve_pct": round(reserve_pct, 1),
        "energy_pct": round(energy_pct, 1),
    }
    total_pct = round(sum(proposed.values()), 1)
    if total_pct != 100.0:
        # Nudge the treasury to close any rounding gap.
        proposed["btc_treasury_pct"] = round(
            proposed["btc_treasury_pct"] + (100.0 - total_pct), 1,
        )

    return {
        "proposed_pct": proposed,
        "proposed_usd": {
            k: round(capital_usd * v / 100.0, 2) for k, v in proposed.items()
        },
        "basis": (
            "Proposal weights available operating lanes by monthly operating "
            "profit per MW (risk profile adjusts reserve and treasury floors). "
            "PROPOSAL ONLY — nothing is executed without human approval."
        ),
        "disclaimer": (
            "This optimizer proposes an allocation. It cannot and will not "
            "trade, spend, or deploy capital. Every lane is conditional on "
            "its stated assumptions and evidence."
        ),
    }
