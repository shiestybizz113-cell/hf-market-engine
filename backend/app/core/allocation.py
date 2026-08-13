"""
Capital Allocation engine — "where should the next $X and Y MW go?"

Compares capital-deployment options for a digital-infrastructure operator on
one normalized economic frame (daily/monthly operating flow, capital deployed,
power consumed, BTC exposure) using live market + network data:

    buy_btc     - spot BTC, no operating flow, full BTC exposure
    mine        - buy ASICs within capital AND power (MW) constraints
    curtail     - sell/curtail power at an energy price assumption
    hold_cash   - cash earning an interest assumption
    buy_gpus    - GPU compute slot (not yet wired; honest 'unavailable')

Options are ranked by monthly operating flow per unit of capital deployed
(capital efficiency) by default; the basis is stated in the output so the
ranking is never presented as a single objective truth. Every option carries
its observed vs assumed inputs for the evidence receipt.

Locked rule: no "ROI". Operating flow and capital basis only.
"""

from typing import Dict, List

from app.core.mining import NetworkData, compute_estimate, network_data_dict

DAYS_PER_MONTH = 30.0
KW_PER_MW = 1000.0


def _mine_risk_flags(est: Dict, electricity_usd_kwh: float) -> List[str]:
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


def _mine_units(capital_usd: float, available_mw: float, asic: Dict) -> int:
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
    asic: Dict,
    btc_price: float,
    network: NetworkData,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    energy_sell_price_usd_kwh: float,
    cash_interest_rate_pct_year: float,
) -> List[Dict]:
    options: List[Dict] = []

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

    # 5) GPU compute slot — surface exists, economics not yet wired
    options.append({
        "key": "buy_gpus",
        "label": "Buy / rent GPUs (AI compute)",
        "available": False,
        "reason": "GPU compute economics not yet wired (build-vs-cloud is a planned lane).",
        "capital_deployed": 0.0,
        "capital_left": capital_usd,
        "power_used_mw": 0.0,
        "btc_exposure": 0.0,
        "flow_day": 0.0,
        "flow_month": 0.0,
        "flow_unit": "usd_month_operating",
        "break_even": None,
        "risk_flags": ["pending_lane"],
        "observed": {},
        "assumptions": {},
    })

    return options


def rank_options(options: List[Dict]) -> List[str]:
    """Rank available options by monthly operating flow per capital deployed.

    Zero-capital options (curtail, hold cash) are ranked on absolute monthly
    flow. The basis is explicit: this is capital efficiency on operating flow,
    not a risk-adjusted or total-return ranking.
    """
    def eff(o: Dict) -> float:
        if not o["available"]:
            return float("-inf")
        if o["capital_deployed"] > 0:
            return o["flow_month"] / o["capital_deployed"]
        return o["flow_month"]

    ordered = sorted([o for o in options if o["available"]], key=eff, reverse=True)
    return [o["key"] for o in ordered]
