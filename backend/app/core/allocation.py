"""
Capital Allocation engine — "where should the next $X and Y MW go?"

Compares capital-deployment options for a digital-infrastructure operator on
one normalized economic frame (daily/monthly operating flow, capital deployed,
power consumed, BTC exposure) using live market + network data:

    buy_btc     - spot BTC, no operating flow, full BTC exposure
    mine        - buy ASICs within capital AND power (MW) constraints
    curtail     - sell/curtail power at an energy price assumption
    hold_cash   - cash earning an interest assumption
    build_gpus  - buy GPUs (AI compute) within capital AND power; rental flow
    cloud_gpus  - rent GPUs (no capex/power); rental-spread flow, zero-capital

GPU rental rates are operator assumptions (no live GPU spot provider is wired)
and are labeled as such. When no achieved rental rate is given, both lanes
default to the catalog cloud-reference rate (zero-margin — no invented profit).

Options are ranked by monthly operating flow per unit of capital deployed
(capital efficiency) by default; the basis is stated in the output so the
ranking is never presented as a single objective truth. Every option carries
its observed vs assumed inputs for the evidence receipt.

Locked rule: no "ROI". Operating flow and capital basis only.
"""


from app.core.gpu import gpu_economics, resolve_gpu
from app.core.mining import NetworkData, compute_estimate, network_data_dict

DAYS_PER_MONTH = 30.0
KW_PER_MW = 1000.0


def _mine_risk_flags(est: dict, electricity_usd_kwh: float) -> list[str]:
    flags = []
    profit = est.get("operating_profit_day")
    be = est.get("break_even_electricity_usd_kwh")
    payback = est.get("simple_payback_days")
    if profit is not None and profit <= 0:
        flags.append("unprofitable")
    if be is not None and electricity_usd_kwh >= be:
        flags.append("below_break_even_electricity")
    if payback is not None and payback > 730:
        flags.append("slow_payback")
    if not flags:
        flags.append("profitable")
    return flags


def _mine_units(capital_usd: float, available_mw: float, asic: dict) -> int:
    if asic["price_usd"] <= 0:
        return 0
    by_capital = int(capital_usd // asic["price_usd"])
    if available_mw > 0:
        kw_per_unit = asic["power_watts"] / 1000.0
        by_power = int((available_mw * KW_PER_MW) // kw_per_unit) if kw_per_unit > 0 else 0
        return min(by_capital, by_power)
    return by_capital


def allocate(
    *,
    capital_usd: float,
    available_mw: float,
    asic: dict,
    btc_price: float,
    network: NetworkData,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    energy_sell_price_usd_kwh: float,
    cash_interest_rate_pct_year: float,
    gpu_model: str = "",
    gpu_capex_usd: float | None = None,
    gpu_power_kw: float | None = None,
    gpu_cloud_rental_usd_per_hr: float | None = None,
    gpu_rental_usd_per_hr: float | None = None,
    gpu_utilization_pct: float = 85.0,
    gpu_uptime_pct: float = 100.0,
    gpu_units_cap: int = 256,
) -> list[dict]:
    options: list[dict] = []

    # 1) Buy BTC outright
    btc_bought = capital_usd / btc_price if btc_price > 0 else 0.0
    options.append({
        "key": "buy_btc",
        "label": "Buy BTC (spot)",
        "available": btc_price > 0,
        "reason": None if btc_price > 0 else "BTC price unavailable",
        "capital_deployed": capital_usd,
        "capital_left": 0.0,
        "power_used_mw": 0.0,
        "btc_exposure": btc_bought,
        "flow_day": 0.0,
        "flow_month": 0.0,
        "flow_unit": "usd_month_operating",
        "break_even": None,
        "risk_flags": ["full_btc_exposure", "no_operating_flow"],
        "observed": {"btc_price": btc_price},
        "assumptions": {},
    })

    # 2) Mine: buy ASICs within capital and power constraints
    units = _mine_units(capital_usd, available_mw, asic)
    if units <= 0:
        options.append({
            "key": "mine",
            "label": f"Mine ({asic['name']})",
            "available": False,
            "reason": (
                "Capital below one unit's cost, or power budget below one unit's draw."
                if available_mw >= 0 else "Unavailable"
            ),
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": 0.0,
            "btc_exposure": 0.0,
            "flow_day": 0.0,
            "flow_month": 0.0,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": ["insufficient_capital_or_power"],
            "observed": {"btc_price": btc_price, "network": network_data_dict(network)},
            "assumptions": {},
        })
    else:
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
        total_hw = units * asic["price_usd"]
        options.append({
            "key": "mine",
            "label": f"Mine ({units}x {asic['name']})",
            "available": True,
            "reason": None,
            "capital_deployed": total_hw,
            "capital_left": max(0.0, capital_usd - total_hw),
            "power_used_mw": units * asic["power_watts"] / (KW_PER_MW * 1000.0),
            "btc_exposure": est["daily_btc"] * units * DAYS_PER_MONTH,
            "flow_day": est["operating_profit_day"] * units,
            "flow_month": est["operating_profit_month"] * units,
            "flow_unit": "usd_month_operating",
            "break_even": est["break_even_electricity_usd_kwh"],
            "risk_flags": _mine_risk_flags(est, electricity_usd_kwh),
            "payback_days": est["simple_payback_days"],
            "capital_basis_usd": total_hw,
            "observed": {"btc_price": btc_price, "network": network_data_dict(network)},
            "assumptions": {
                "electricity_usd_kwh": electricity_usd_kwh,
                "pool_fee_pct": pool_fee_pct,
                "uptime_pct": uptime_pct,
                "asic_price_usd": asic["price_usd"],
                "hardware_resale_value_usd": 0,
            },
        })

    # 3) Curtail / sell power at an energy price assumption
    if energy_sell_price_usd_kwh > 0 and available_mw > 0:
        daily_kwh = available_mw * KW_PER_MW * 24.0
        daily_rev = daily_kwh * energy_sell_price_usd_kwh
        options.append({
            "key": "curtail",
            "label": f"Curtail / sell power ({available_mw} MW @ ${energy_sell_price_usd_kwh}/kWh)",
            "available": True,
            "reason": None,
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": available_mw,
            "btc_exposure": 0.0,
            "flow_day": daily_rev,
            "flow_month": daily_rev * DAYS_PER_MONTH,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": ["power_price_assumed"],
            "observed": {"available_mw": available_mw},
            "assumptions": {"energy_sell_price_usd_kwh": energy_sell_price_usd_kwh},
        })
    else:
        options.append({
            "key": "curtail",
            "label": "Curtail / sell power",
            "available": False,
            "reason": "No MW budget or no energy sell price set.",
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": 0.0,
            "btc_exposure": 0.0,
            "flow_day": 0.0,
            "flow_month": 0.0,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": [],
            "observed": {"available_mw": available_mw},
            "assumptions": {"energy_sell_price_usd_kwh": energy_sell_price_usd_kwh},
        })

    # 4) Hold cash at an interest assumption
    monthly_rate = cash_interest_rate_pct_year / 100.0 / 12.0
    options.append({
        "key": "hold_cash",
        "label": f"Hold cash ({cash_interest_rate_pct_year:g}%/yr)",
        "available": True,
        "reason": None,
        "capital_deployed": capital_usd,
        "capital_left": 0.0,
        "power_used_mw": 0.0,
        "btc_exposure": 0.0,
        "flow_day": capital_usd * monthly_rate / DAYS_PER_MONTH,
        "flow_month": capital_usd * monthly_rate,
        "flow_unit": "usd_month_operating",
        "break_even": None,
        "risk_flags": ["cash_interest_assumed"],
        "observed": {},
        "assumptions": {"cash_interest_rate_pct_year": cash_interest_rate_pct_year},
    })

    # 5) GPUs: build vs cloud (AI compute economics lane)
    options.extend(gpu_lanes(
        capital_usd=capital_usd,
        available_mw=available_mw,
        electricity_usd_kwh=electricity_usd_kwh,
        gpu_model=gpu_model,
        gpu_capex_usd=gpu_capex_usd,
        gpu_power_kw=gpu_power_kw,
        gpu_cloud_rental_usd_per_hr=gpu_cloud_rental_usd_per_hr,
        gpu_rental_usd_per_hr=gpu_rental_usd_per_hr,
        gpu_utilization_pct=gpu_utilization_pct,
        gpu_uptime_pct=gpu_uptime_pct,
        gpu_units_cap=gpu_units_cap,
    ))

    return options


def gpu_lanes(
    *,
    capital_usd: float,
    available_mw: float,
    electricity_usd_kwh: float,
    gpu_model: str,
    gpu_capex_usd: float | None,
    gpu_power_kw: float | None,
    gpu_cloud_rental_usd_per_hr: float | None,
    gpu_rental_usd_per_hr: float | None,
    gpu_utilization_pct: float,
    gpu_uptime_pct: float,
    gpu_units_cap: int,
) -> list[dict]:
    """Build the build_gpus + cloud_gpus option dicts.

    Same shape as other allocation options plus a per_unit economics dict (the
    allocation response model ignores the extra key; the standalone GPU
    economics endpoint uses it). Every GPU number is an operator assumption —
    no live GPU spot provider is wired.
    """
    gpu = resolve_gpu(
        gpu_model or None,
        gpu_capex_usd,
        gpu_power_kw,
        gpu_cloud_rental_usd_per_hr,
    )
    gpu_active = gpu.get("present", False)
    achieved_rate = gpu_rental_usd_per_hr
    cloud_rate = gpu.get("cloud_rental_usd_hr")
    if gpu_active and achieved_rate is None:
        # Conservative default: achieve exactly the market cloud reference
        # rate. No invented margin.
        achieved_rate = cloud_rate
    gpu_assumptions = {
        "gpu_model": gpu.get("model"),
        "gpu_capex_usd": gpu.get("capex_usd"),
        "gpu_power_kw": gpu.get("power_kw"),
        "gpu_achieved_rental_usd_hr": achieved_rate,
        "gpu_cloud_rental_usd_hr": cloud_rate,
        "gpu_utilization_pct": gpu_utilization_pct,
        "gpu_uptime_pct": gpu_uptime_pct,
        "gpu_units_cap": gpu_units_cap,
    }
    lanes: list[dict] = []

    if not gpu_active:
        lanes.append({
            "key": "build_gpus",
            "label": "Build GPUs (AI compute)",
            "available": False,
            "reason": "No GPU model selected (set gpu_model or gpu_capex_usd + gpu_power_kw).",
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": 0.0,
            "btc_exposure": 0.0,
            "flow_day": 0.0,
            "flow_month": 0.0,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": ["pending_inputs"],
            "observed": {"available_mw": available_mw},
            "assumptions": gpu_assumptions,
        })
        lanes.append({
            "key": "cloud_gpus",
            "label": "Rent GPUs in cloud (AI compute)",
            "available": False,
            "reason": "No GPU model selected (set gpu_model or gpu_capex_usd).",
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": 0.0,
            "btc_exposure": 0.0,
            "flow_day": 0.0,
            "flow_month": 0.0,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": ["pending_inputs"],
            "observed": {"available_mw": available_mw},
            "assumptions": gpu_assumptions,
        })
    else:
        # --- 5a) Build: buy GPUs within capital AND power constraints ---
        units_by_capital = (
            int(capital_usd // gpu["capex_usd"]) if gpu["capex_usd"] > 0 else 0
        )
        units_by_power = 0
        if available_mw > 0 and gpu["power_kw"] > 0:
            units_by_power = int(
                (available_mw * KW_PER_MW) // gpu["power_kw"]
            )
        units = min(gpu_units_cap, units_by_capital)
        if available_mw > 0:
            units = min(units, units_by_power)

        if units <= 0:
            lanes.append({
                "key": "build_gpus",
                "label": f"Build GPUs ({gpu['model']})",
                "available": False,
                "reason": (
                    "Capital below one GPU's cost, or power budget below one GPU's draw."
                    if available_mw >= 0 else "Unavailable"
                ),
                "capital_deployed": 0.0,
                "capital_left": capital_usd,
                "power_used_mw": 0.0,
                "btc_exposure": 0.0,
                "flow_day": 0.0,
                "flow_month": 0.0,
                "flow_unit": "usd_month_operating",
                "break_even": None,
                "risk_flags": ["insufficient_capital_or_power"],
                "observed": {"available_mw": available_mw},
                "assumptions": gpu_assumptions,
            })
        else:
            gest = gpu_economics(
                gpu=gpu,
                achieved_rental_usd_hr=achieved_rate,
                cloud_rental_usd_hr=cloud_rate,
                utilization_pct=gpu_utilization_pct,
                uptime_pct=gpu_uptime_pct,
                electricity_usd_kwh=electricity_usd_kwh,
            )
            total_hw = units * gpu["capex_usd"]
            flags = ["gpu_economics_assumed"]
            if gest["build_profit_day"] <= 0:
                flags.append("unprofitable")
            if gest["build_payback_days"] is not None and gest["build_payback_days"] > 730:
                flags.append("slow_payback")
            lanes.append({
                "key": "build_gpus",
                "label": f"Build GPUs ({units}x {gpu['model']})",
                "available": True,
                "reason": None,
                "capital_deployed": total_hw,
                "capital_left": max(0.0, capital_usd - total_hw),
                "power_used_mw": units * gpu["power_kw"] / KW_PER_MW,
                "btc_exposure": 0.0,
                "flow_day": gest["build_profit_day"] * units,
                "flow_month": gest["build_profit_month"] * units,
                "flow_unit": "usd_month_operating",
                "break_even": None,
                "risk_flags": flags,
                "payback_days": gest["build_payback_days"],
                "capital_basis_usd": total_hw,
                "per_unit": gest,
                "observed": {"available_mw": available_mw},
                "assumptions": gpu_assumptions,
            })

        # --- 5b) Cloud: rent GPUs (no capex, no power) ---
        # No capital or power constraint applies; the operator's addressable
        # GPU demand (gpu_units_cap) is the only bound — an explicit assumption.
        units_cloud = max(1, gpu_units_cap)
        gest = gpu_economics(
            gpu=gpu,
            achieved_rental_usd_hr=achieved_rate,
            cloud_rental_usd_hr=cloud_rate,
            utilization_pct=gpu_utilization_pct,
            uptime_pct=gpu_uptime_pct,
            electricity_usd_kwh=electricity_usd_kwh,
        )
        cloud_flags = ["gpu_economics_assumed"]
        if gest["cloud_profit_day"] < 0:
            cloud_flags.append("negative_margin")
        lanes.append({
            "key": "cloud_gpus",
            "label": f"Rent GPUs in cloud ({units_cloud}x {gpu['model']})",
            "available": True,
            "reason": None,
            "capital_deployed": 0.0,
            "capital_left": capital_usd,
            "power_used_mw": 0.0,
            "btc_exposure": 0.0,
            "flow_day": gest["cloud_profit_day"] * units_cloud,
            "flow_month": gest["cloud_profit_month"] * units_cloud,
            "flow_unit": "usd_month_operating",
            "break_even": None,
            "risk_flags": cloud_flags,
            "per_unit": gest,
            "observed": {"available_mw": available_mw},
            "assumptions": gpu_assumptions,
        })

    return lanes


def rank_options(options: list[dict]) -> list[str]:
    """Rank available options by monthly operating flow per capital deployed.

    Zero-capital options (curtail, hold cash) are ranked on absolute monthly
    flow. The basis is explicit: this is capital efficiency on operating flow,
    not a risk-adjusted or total-return ranking.
    """
    def eff(o: dict) -> float:
        if not o["available"]:
            return float("-inf")
        if o["capital_deployed"] > 0:
            return o["flow_month"] / o["capital_deployed"]
        return o["flow_month"]

    ordered = sorted([o for o in options if o["available"]], key=eff, reverse=True)
    return [o["key"] for o in ordered]
