"""SecDB-style N-dimensional capital risk grid.

Sweeps the canonical capital engine across any subset of outcome dimensions
(price, difficulty, power, uptime, GPU utilization/rental, energy sale, rates)
producing a what-if matrix where every cell is computed by the same
``run_capital_allocation`` + integrity pipeline as the base run. The default
``tornado`` mode moves one dimension at a time (others pinned at base) and
derives a per-dimension breakeven surface: the value at which the best
operating lane stops producing operating profit. ``joint`` mode computes the
full cross-product (capped) for true N-dimensional what-if analysis.

Evidence semantics match the rest of the Capital V2 fabric: shocks are
simulation/assumption state, never merged into a fake live number, and each
cell carries fleet-aware integrity corrections.
"""

import itertools

from app.core.capital_allocation import _rank_lanes, run_capital_allocation
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.capital_scenarios_v2 import _shift_network

DEFAULT_CELL_CAP = 1248

DIMENSION_SPECS: dict[str, dict] = {
    "btc_price_shift_pct": {
        "label": "BTC horizon price",
        "min": -50.0,
        "max": 50.0,
        "max_steps": 13,
        "default_steps": 9,
    },
    "btc_price_at_horizon": {
        "label": "BTC @ horizon",
        "min": 0.0,
        "max": 500000.0,
        "max_steps": 13,
        "default_steps": 9,
    },
    "electricity_usd_kwh": {
        "label": "Electricity ($/kWh)",
        "min": 0.0,
        "max": 0.50,
        "max_steps": 13,
        "default_steps": 9,
    },
    "difficulty_growth_pct_year": {
        "label": "Difficulty growth (%/yr)",
        "min": 0.0,
        "max": 100.0,
        "max_steps": 13,
        "default_steps": 9,
    },
    "difficulty_shift_pct": {
        "label": "Difficulty shock",
        "min": -50.0,
        "max": 50.0,
        "max_steps": 13,
        "default_steps": 9,
    },
    "uptime_pct": {
        "label": "Mining uptime (%)",
        "min": 50.0,
        "max": 100.0,
        "max_steps": 11,
        "default_steps": 7,
    },
    "gpu_utilization_pct": {
        "label": "GPU utilization (%)",
        "min": 30.0,
        "max": 100.0,
        "max_steps": 11,
        "default_steps": 7,
    },
    "gpu_rental_usd_per_hr": {
        "label": "GPU rental ($/hr)",
        "min": 0.0,
        "max": 10.0,
        "max_steps": 11,
        "default_steps": 7,
    },
    "energy_sell_price_usd_kwh": {
        "label": "Energy sell ($/kWh)",
        "min": 0.0,
        "max": 0.30,
        "max_steps": 11,
        "default_steps": 7,
    },
    "cash_interest_rate_pct_year": {
        "label": "Cash rate (%/yr)",
        "min": 0.0,
        "max": 15.0,
        "max_steps": 11,
        "default_steps": 7,
    },
}


def _linspace(min_v: float, max_v: float, steps: int) -> list[float]:
    if steps <= 1:
        return [min_v]
    step = (max_v - min_v) / (steps - 1)
    return [round(min_v + step * i, 6) for i in range(steps)]


def validate_grid(grid: dict[str, dict], *, cell_cap: int = DEFAULT_CELL_CAP) -> list[dict]:
    """Normalize and validate a grid spec.

    Returns ordered dimension definitions ``{key, label, min, max, steps,
    values}``. Raises ValueError with a human-readable message on unknown
    dimensions, inverted ranges, absurd step counts, or an over-cap cell
    count.
    """
    specs: list[dict] = []
    total = 1
    for key, axis in grid.items():
        spec = DIMENSION_SPECS.get(key)
        if spec is None:
            raise ValueError(
                f"Unknown grid dimension '{key}'. Choose from: {', '.join(sorted(DIMENSION_SPECS))}"
            )
        lo = float(axis.get("min", spec["min"]))
        hi = float(axis.get("max", spec["max"]))
        steps = int(axis.get("steps", spec["default_steps"]))
        if hi < lo:
            raise ValueError(f"Grid dimension '{key}': max ({hi}) must be >= min ({lo}).")
        if steps < 2 or steps > spec["max_steps"]:
            raise ValueError(
                f"Grid dimension '{key}': steps must be in [2, {spec['max_steps']}]."
            )
        values = _linspace(lo, hi, steps)
        total *= steps
        if total > cell_cap:
            raise ValueError(
                f"Grid cell count {total} exceeds the {cell_cap}-cell cap. "
                "Reduce steps or sweep fewer dimensions jointly."
            )
        specs.append({"key": key, "label": spec["label"], "min": lo, "max": hi, "steps": steps, "values": values})
    if not specs:
        raise ValueError("Grid requires at least one dimension.")
    return specs


def _cell_vector(base: dict, key: str, value: float) -> dict:
    """Map a grid (dimension, value) onto the subset of engine inputs it shocks."""
    inputs = base["inputs"]
    observed = base["observed"]
    if key == "btc_price_shift_pct":
        spot = float(observed["btc_price"])
        horizon = float(inputs.get("btc_price_at_horizon") or spot)
        return {"btc_price_at_horizon": horizon * (1.0 + value / 100.0)}
    if key == "btc_price_at_horizon":
        return {"btc_price_at_horizon": value}
    if key == "electricity_usd_kwh":
        return {"electricity_usd_kwh": value}
    if key == "difficulty_growth_pct_year":
        return {"difficulty_growth_pct_year": value}
    if key == "difficulty_shift_pct":
        return {"difficulty_shift_pct": value}
    if key == "uptime_pct":
        return {"uptime_pct": value}
    if key == "gpu_utilization_pct":
        return {"gpu_utilization_pct": max(0.0, min(100.0, value))}
    if key == "gpu_rental_usd_per_hr":
        return {"gpu_rental_usd_per_hr": value}
    if key == "energy_sell_price_usd_kwh":
        return {"energy_sell_price_usd_kwh": value}
    if key == "cash_interest_rate_pct_year":
        return {"cash_interest_rate_pct_year": value}
    raise ValueError(f"Unknown grid dimension '{key}'.")


def run_capital_risk_grid(
    *,
    base: dict,
    grid: dict[str, dict],
    owned: dict | None = None,
    joint: bool = False,
    cell_cap: int = DEFAULT_CELL_CAP,
) -> dict:
    """Run the what-if grid against a prepared Capital base result.

    ``base`` is the output of a Capital V2 run (shape produced by the
    ``/capital/run`` path: ``inputs``, ``observed``, ``lanes``, ``ranking``).
    Returns ``{mode, dimensions, cell_count, cells, breakeven}`` where each
    cell mirrors a ``capital_scenarios_v2`` row plus the dimension/value that
    produced it, and ``breakeven`` maps every swept dimension to the value at
    which the best operating lane stops producing operating profit (tornado
    mode only, since joint interactions are ambiguous to attribute).
    """
    specs = validate_grid(grid, cell_cap=cell_cap)
    base_inputs = base["inputs"]
    base_observed = base["observed"]

    def run_cell(overrides: dict) -> dict:
        btc_shift = float(overrides.get("difficulty_shift_pct", 0.0))
        network_dict = base_observed.get("network")
        difficulty = None
        if network_dict:
            difficulty = float(network_dict["difficulty"]) * (1.0 + btc_shift / 100.0)

        res = run_capital_allocation(
            capital_usd=base_inputs["capital_usd"],
            available_mw=base_inputs["available_mw"],
            horizon_months=base_inputs["horizon_months"],
            electricity_usd_kwh=float(overrides.get("electricity_usd_kwh", base_inputs["electricity_usd_kwh"])),
            risk_profile=base_inputs["risk_profile"],
            network=None if difficulty is None else _shift_network(network_dict, difficulty),
            btc_price=float(base_observed["btc_price"]),
            btc_price_provider=base_observed["btc_price_provider"],
            simulation=base_inputs.get("simulation", False),
            asic=base_inputs.get("asic", {}),
            pool_fee_pct=base_inputs.get("pool_fee_pct", 1.0),
            uptime_pct=float(overrides.get("uptime_pct", base_inputs.get("uptime_pct", 95.0))),
            btc_price_at_horizon=float(
                overrides.get("btc_price_at_horizon", base_inputs.get("btc_price_at_horizon") or base_observed["btc_price"])
            ),
            difficulty_growth_pct_year=float(
                overrides.get("difficulty_growth_pct_year", base_inputs.get("difficulty_growth_pct_year", 20.0))
            ),
            gpu_model=base_inputs.get("gpu_model", ""),
            gpu_capex_usd=base_inputs.get("gpu_capex_usd"),
            gpu_power_kw=base_inputs.get("gpu_power_kw"),
            gpu_cloud_rental_usd_per_hr=base_inputs.get("gpu_cloud_rental_usd_per_hr"),
            gpu_rental_usd_per_hr=(
                float(overrides["gpu_rental_usd_per_hr"])
                if "gpu_rental_usd_per_hr" in overrides
                else base_inputs.get("gpu_rental_usd_per_hr")
            ),
            gpu_utilization_pct=float(overrides.get("gpu_utilization_pct", base_inputs.get("gpu_utilization_pct", 85.0))),
            gpu_uptime_pct=base_inputs.get("gpu_uptime_pct", 100.0),
            gpu_units_cap=base_inputs.get("gpu_units_cap", 256),
            gpu_pue=base_inputs.get("gpu_pue", 1.3),
            energy_acquisition_usd_kwh=base_inputs.get("energy_acquisition_usd_kwh"),
            energy_sell_price_usd_kwh=(
                float(overrides["energy_sell_price_usd_kwh"])
                if "energy_sell_price_usd_kwh" in overrides
                else base_inputs.get("energy_sell_price_usd_kwh")
            ),
            energy_utilization_pct=base_inputs.get("energy_utilization_pct", 100.0),
            storage_mwh=base_inputs.get("storage_mwh", 0.0),
            storage_capex_usd_per_mwh=base_inputs.get("storage_capex_usd_per_mwh", 0.0),
            storage_roundtrip_pct=base_inputs.get("storage_roundtrip_pct", 85.0),
            cash_interest_rate_pct_year=float(overrides.get("cash_interest_rate_pct_year", base_inputs.get("cash_interest_rate_pct_year", 4.0))),
            owned=owned,
        )
        apply_energy_storage_integrity(res)

        matrix: dict[str, dict] = {}
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
        return res, matrix

    cells: list[dict] = []
    breakeven: dict[str, dict] = {}

    if joint:
        value_lists = [spec["values"] for spec in specs]
        for combo in itertools.product(*value_lists):
            overrides: dict = {}
            for spec, value in zip(specs, combo, strict=False):
                overrides.update(_cell_vector(base, spec["key"], value))
            overrides["_vector"] = dict(zip([s["key"] for s in specs], combo, strict=False))
            res, matrix = run_cell(overrides)
            cells.append(_pack_cell(overrides["_vector"], res, matrix, base))
    else:
        top = _rank_lanes(base["lanes"])[0] if base.get("lanes") else None
        for spec in specs:
            key = spec["key"]
            dim_cells: list[dict] = []
            for value in spec["values"]:
                overrides = _cell_vector(base, key, value)
                overrides["_vector"] = {key: value}
                res, matrix = run_cell(overrides)
                cell = _pack_cell(overrides["_vector"], res, matrix, base)
                cells.append(cell)
                dim_cells.append(cell)
            breakeven[key] = _breakeven(dim_cells, top_lane=top or "mining")

    return {
        "mode": "joint" if joint else "tornado",
        "dimensions": [{"key": s["key"], "label": s["label"], "min": s["min"], "max": s["max"], "steps": s["steps"]} for s in specs],
        "cell_count": len(cells),
        "cells": cells,
        "breakeven": breakeven,
    }


def _pack_cell(vector: dict, res: dict, matrix: dict, base: dict) -> dict:
    top = _rank_lanes(res["lanes"])[0] if res.get("lanes") else None
    top_lane = matrix.get(top, {}) if top else {}
    return {
        "vector": vector,
        "btc_price": res["observed"]["btc_price"],
        "btc_price_at_horizon": res["inputs"].get("btc_price_at_horizon"),
        "difficulty": res["observed"].get("network", {}).get("difficulty"),
        "top_lane": top,
        "top_operating_profit_month": top_lane.get("operating_profit_month"),
        "lanes": matrix,
    }


def _breakeven(cells: list[dict], *, top_lane: str) -> dict:
    """Interpolate where the best operating lane flips to non-positive flow."""
    profits: list[tuple[float, float]] = []
    for cell in cells:
        profit = None
        lane = cell["lanes"].get(top_lane, {})
        if lane.get("available"):
            profit = lane.get("operating_profit_month")
        if profit is None:
            continue
        profits.append((float(list(cell["vector"].values())[0]), float(profit)))

    if not profits:
        return {"top_lane": top_lane, "breakeven_value": None, "note": "No operating flow to cross."}

    base_profit = profits[0][1]
    if base_profit <= 0:
        return {"top_lane": top_lane, "breakeven_value": None, "note": "Lane already non-profitable at base."}
    for i in range(1, len(profits)):
        x0, p0 = profits[i - 1]
        x1, p1 = profits[i]
        if p1 <= 0 < p0:
            t = p0 / (p0 - p1) if p0 != p1 else 0.5
            return {
                "top_lane": top_lane,
                "breakeven_value": round(x0 + (x1 - x0) * t, 4),
                "note": "Linear interpolation across the profit crossover.",
            }
    return {"top_lane": top_lane, "breakeven_value": None, "note": "Lane remains profitable across the whole sweep."}
