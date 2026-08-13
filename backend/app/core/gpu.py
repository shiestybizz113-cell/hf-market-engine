"""
GPU / AI compute economics — build-vs-cloud lane.

Mirrors the ASIC catalog philosophy: indicative reference hardware with
street/rental rates that are treated as user-editable inputs, not live quotes.
There is no live GPU spot provider wired (unlike BTC via CoinGecko and the
mining network via blockchain.info), so every GPU number is an assumption and
is labeled as such in the allocation options and evidence receipts.

Lane semantics (honesty contract, no ROI):
    build_gpus - buy GPUs within capital AND power (MW); operating flow is
                 rental revenue (achieved $/GPU-hr) minus power cost; simple
                 payback on GPU capex when flow is positive.
    cloud_gpus - rent GPUs (no capex, no power); operating flow is the spread
                 between achieved rental and cloud rental over billable hours.
                 Zero-capital option — ranks on absolute monthly flow.

Default rental rates: when the operator does not state an achieved rate, the
catalog cloud-reference rate is used for BOTH lanes (zero-margin assumption —
no synthetic profitability is invented).
"""

from typing import Dict, Optional

HOURS_PER_DAY = 24.0
DAYS_PER_MONTH = 30.0
KW_PER_MW = 1000.0

# ---------- GPU catalog ----------
# Reference hardware + indicative street capex and cloud rental (market
# reference, user-editable inputs, NOT live quotes). Power draws are TGP.
GPU_CATALOG: Dict[str, dict] = {
    "H100": {"model": "NVIDIA H100 SXM (80GB)", "power_kw": 0.700, "capex_usd": 25000.0, "cloud_rental_usd_hr": 2.50},
    "H200": {"model": "NVIDIA H200 (141GB)", "power_kw": 0.700, "capex_usd": 30000.0, "cloud_rental_usd_hr": 3.00},
    "B200": {"model": "NVIDIA B200 (192GB)", "power_kw": 1.000, "capex_usd": 40000.0, "cloud_rental_usd_hr": 4.00},
    "A100": {"model": "NVIDIA A100 80GB", "power_kw": 0.400, "capex_usd": 12000.0, "cloud_rental_usd_hr": 1.40},
    "L40S": {"model": "NVIDIA L40S", "power_kw": 0.350, "capex_usd": 8000.0, "cloud_rental_usd_hr": 0.90},
    "4090": {"model": "NVIDIA RTX 4090", "power_kw": 0.450, "capex_usd": 2200.0, "cloud_rental_usd_hr": 0.40},
}


def gpu_for(model: str) -> Optional[dict]:
    return GPU_CATALOG.get(model) or next(
        (v for v in GPU_CATALOG.values() if v["model"].lower() == model.lower()), None
    )


def resolve_gpu(
    model: Optional[str],
    capex_usd: Optional[float],
    power_kw: Optional[float],
    cloud_rental_usd_hr: Optional[float],
) -> Dict:
    """Build the effective GPU spec from catalog + user overrides.

    Returns None-equivalent via raise? No — returns a dict; callers check
    whether a model/custom spec was provided by testing `spec.get("present")`.
    """
    spec: Dict = {"present": False}
    if model:
        item = gpu_for(model)
        if item:
            spec = dict(item)
            spec["present"] = True
    if capex_usd is not None:
        spec["capex_usd"] = capex_usd
    if power_kw is not None:
        spec["power_kw"] = power_kw
    if cloud_rental_usd_hr is not None:
        spec["cloud_rental_usd_hr"] = cloud_rental_usd_hr
    return spec


def gpu_economics(
    *,
    gpu: Dict,
    achieved_rental_usd_hr: float,
    cloud_rental_usd_hr: float,
    utilization_pct: float,
    uptime_pct: float,
    electricity_usd_kwh: float,
    pue: float = 1.0,
) -> Dict:
    """Per-GPU economics on the SAME frame as mining compute_estimate.

    billable_hours = uptime_hours * utilization (fraction of installed time
    that is rented/sold). Power is drawn for the full uptime window (a running
    GPU still idles-draws), a conservative assumption stated in the output.
    ``pue`` scales total facility power (cooling/overheads) on top of GPU TGP.

    Returns build + cloud flow for ONE unit; callers scale by count.
    """
    uptime = max(0.0, min(100.0, uptime_pct))
    utilization = max(0.0, min(100.0, utilization_pct))
    uptime_hrs_day = HOURS_PER_DAY * (uptime / 100.0)
    billable_hrs_day = uptime_hrs_day * (utilization / 100.0)

    revenue_day = achieved_rental_usd_hr * billable_hrs_day
    power_kwh_day = gpu["power_kw"] * uptime_hrs_day
    power_cost_day = power_kwh_day * electricity_usd_kwh * pue
    build_profit_day = revenue_day - power_cost_day
    build_payback_days = (
        gpu["capex_usd"] / build_profit_day if build_profit_day > 0 else None
    )
    cloud_profit_day = (achieved_rental_usd_hr - cloud_rental_usd_hr) * billable_hrs_day

    return {
        "billable_hrs_day": billable_hrs_day,
        "power_kwh_day": power_kwh_day,
        "revenue_day": revenue_day,
        "power_cost_day": power_cost_day,
        "build_profit_day": build_profit_day,
        "build_profit_month": build_profit_day * DAYS_PER_MONTH,
        "build_payback_days": build_payback_days,
        "cloud_profit_day": cloud_profit_day,
        "cloud_profit_month": cloud_profit_day * DAYS_PER_MONTH,
        "capex_usd": gpu["capex_usd"],
        "capital_basis_usd": gpu["capex_usd"],
        "pue": pue,
        "roi_label": (
            "Not computed: full ROI requires hosting, downtime, resale and "
            "horizon assumptions. Only operating profit and simple hardware "
            "payback are reported."
        ),
    }
