"""
SecDB-style scenario engine — N-dimensional what-if over mining economics.

A scenario is a vector over the inputs that actually drive mining cash flow:

    btc_price_shift_pct     (market)
    difficulty_shift_pct    (network)
    electricity_usd_kwh     (energy)
    uptime_pct              (operations)

Each vector is applied to live data (BTC price + network) and produces full
operating economics plus explicit risk flags. Named presets give institutional
users a one-click "run the stress case" without building a custom vector.

Evidence contract: every run is grounded in live observed data when the mode is
live (demo otherwise) and the receipt separates observed from assumptions.
"""


from app.core.mining import (
    NetworkData,
    compute_estimate,
)

# Named institutional scenarios. Each is a full vector (not just price), so the
# stress case is "everything moves against you", not a one-variable shock.
SCENARIO_PRESETS: dict[str, dict] = {
    "stress": {
        "label": "Stress — BTC falls, difficulty rises, power up, uptime down",
        "btc_price_shift_pct": -25.0,
        "difficulty_shift_pct": 8.0,
        "electricity_usd_kwh": 0.095,
        "uptime_pct": 91.0,
    },
    "halving_rally": {
        "label": "Halving rally — price rips but difficulty chases it",
        "btc_price_shift_pct": 50.0,
        "difficulty_shift_pct": 25.0,
        "electricity_usd_kwh": 0.10,
        "uptime_pct": 95.0,
    },
    "power_squeeze": {
        "label": "Power squeeze — energy up 25%, price soft",
        "btc_price_shift_pct": -10.0,
        "difficulty_shift_pct": 0.0,
        "electricity_usd_kwh": 0.125,
        "uptime_pct": 95.0,
    },
    "goldilocks": {
        "label": "Goldilocks — cheap power, high uptime, modest rally",
        "btc_price_shift_pct": 10.0,
        "difficulty_shift_pct": 5.0,
        "electricity_usd_kwh": 0.08,
        "uptime_pct": 97.0,
    },
}


def _risk_flags(est: dict, electricity_usd_kwh: float) -> list[str]:
    """Honest, mechanical risk labels. No single 'score' — a list of facts."""
    flags = []
    profit = est.get("operating_profit_day")
    be = est.get("break_even_electricity_usd_kwh")
    payback = est.get("simple_payback_days")

    if profit is None:
        flags.append("no_estimate")
    else:
        if profit <= 0:
            flags.append("unprofitable")
        else:
            if be is not None and electricity_usd_kwh >= be:
                flags.append("below_break_even_electricity")
            if payback is not None and payback > 730:
                flags.append("slow_payback")
            if payback is None or payback <= 365:
                flags.append("payback_within_year")
            if not flags:
                flags.append("profitable")
    return flags or ["unknown"]


def run_scenario_vector(
    *,
    asic: dict,
    network: NetworkData,
    btc_price: float,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    btc_price_shift_pct: float = 0.0,
    difficulty_shift_pct: float = 0.0,
    label: str | None = None,
) -> dict:
    """Apply one scenario vector to a rig and return economics + risk."""
    scenario_price = btc_price * (1 + btc_price_shift_pct / 100.0)
    scenario_diff = network.difficulty * (1 + difficulty_shift_pct / 100.0)
    scenario_net = NetworkData(
        provider=network.provider,
        source=network.source,
        observed_at=network.observed_at,
        hashrate_ths=network.hashrate_ths,
        difficulty=scenario_diff,
        block_subsidy=network.block_subsidy,
        block_time_seconds=network.block_time_seconds,
    )
    est = compute_estimate(
        hashrate_ths=asic["hashrate_ths"],
        power_watts=asic["power_watts"],
        electricity_usd_kwh=electricity_usd_kwh,
        pool_fee_pct=pool_fee_pct,
        uptime_pct=uptime_pct,
        btc_price=scenario_price,
        hardware_cost_usd=asic["price_usd"],
        network=scenario_net,
    )
    return {
        "label": label or f"BTC {btc_price_shift_pct:+.0f}% / diff {difficulty_shift_pct:+.0f}%",
        "vector": {
            "btc_price_shift_pct": btc_price_shift_pct,
            "difficulty_shift_pct": difficulty_shift_pct,
            "electricity_usd_kwh": electricity_usd_kwh,
            "uptime_pct": uptime_pct,
        },
        "btc_price": scenario_price,
        "difficulty": scenario_diff,
        "estimates": est,
        "risk_flags": _risk_flags(est, electricity_usd_kwh),
        "risk": (
            "unprofitable" if est.get("operating_profit_day") is not None
            and est["operating_profit_day"] <= 0 else
            "profitable" if est.get("operating_profit_day") else "unknown"
        ),
    }


def run_scenario_set(
    *,
    asic: dict,
    network: NetworkData,
    btc_price: float,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    scenarios: list[dict],
) -> list[dict]:
    """Run many vectors; base electricity/uptime act as defaults per vector."""
    out = []
    for s in scenarios:
        out.append(run_scenario_vector(
            asic=asic,
            network=network,
            btc_price=btc_price,
            electricity_usd_kwh=s.get("electricity_usd_kwh", electricity_usd_kwh),
            pool_fee_pct=pool_fee_pct,
            uptime_pct=s.get("uptime_pct", uptime_pct),
            btc_price_shift_pct=s.get("btc_price_shift_pct", 0.0),
            difficulty_shift_pct=s.get("difficulty_shift_pct", 0.0),
            label=s.get("label"),
        ))
    return out
