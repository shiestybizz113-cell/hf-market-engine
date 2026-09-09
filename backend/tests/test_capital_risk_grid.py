"""Risk-grid engine tests: query validation, cell math invariants, breakeven.

Pure-engine tests only — no DB, no HTTP. The canonical base run is built with
``run_capital_allocation`` exactly as the API does, then the grid sweeps it.
"""

import unittest
from datetime import UTC, datetime

from app.core.capital_allocation import run_capital_allocation
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.capital_risk_grid import (
    DEFAULT_CELL_CAP,
    run_capital_risk_grid,
    validate_grid,
)
from app.core.mining import NetworkData


def _base_run(**overrides) -> dict:
    params = dict(
        capital_usd=1_000_000,
        available_mw=1.0,
        horizon_months=12,
        electricity_usd_kwh=0.05,
        risk_profile="balanced",
        network=NetworkData(
            provider="test",
            source="live",
            observed_at=datetime.now(UTC),
            hashrate_ths=600.0,
            difficulty=80e12,
            block_subsidy=3.125,
            block_time_seconds=600.0,
        ),
        btc_price=60_000,
        btc_price_provider="test",
        simulation=True,
        asic={"model": "S21 Pro", "hashrate_ths": 234, "power_watts": 3510, "price_usd": 4500},
        pool_fee_pct=1.0,
        uptime_pct=95.0,
        btc_price_at_horizon=80_000,
        difficulty_growth_pct_year=20.0,
        gpu_model="H100",
        gpu_capex_usd=25_000,
        gpu_power_kw=0.7,
        gpu_cloud_rental_usd_per_hr=None,
        gpu_rental_usd_per_hr=2.0,
        gpu_utilization_pct=85.0,
        gpu_uptime_pct=100.0,
        gpu_units_cap=256,
        gpu_pue=1.3,
        energy_acquisition_usd_kwh=0.03,
        energy_sell_price_usd_kwh=0.09,
        energy_utilization_pct=100.0,
        storage_mwh=1.0,
        storage_capex_usd_per_mwh=5_000.0,
        storage_roundtrip_pct=85.0,
        cash_interest_rate_pct_year=4.0,
        owned={},
    )
    params.update(overrides)
    res = run_capital_allocation(**params)
    apply_energy_storage_integrity(res)
    res["ranking"] = ["gpu", "mining", "energy", "btc"]
    res["inputs"] = params
    res["observed"] = {
        "btc_price": 60_000,
        "btc_price_provider": "test",
        "network": {
            "provider": "test",
            "source": "live",
            "hashrate_ths": 600.0,
            "difficulty": 80e12,
            "block_subsidy": 3.125,
            "block_time_seconds": 600.0,
        },
    }
    return res


class ValidateGridTests(unittest.TestCase):
    def test_unknown_dimension_rejected(self):
        with self.assertRaises(ValueError):
            validate_grid({"moon_price_pct": {"steps": 3}})

    def test_inverted_range_rejected(self):
        with self.assertRaises(ValueError):
            validate_grid({"btc_price_shift_pct": {"min": 50, "max": -50, "steps": 3}})

    def test_blank_grid_rejected(self):
        with self.assertRaises(ValueError):
            validate_grid({})

    def test_cell_cap_enforced(self):
        with self.assertRaises(ValueError) as ctx:
            validate_grid(
                {
                    "btc_price_shift_pct": {"min": -25, "max": 50, "steps": 3},
                    "electricity_usd_kwh": {"min": 0.02, "max": 0.15, "steps": 3},
                    "uptime_pct": {"min": 60, "max": 99, "steps": 3},
                    "gpu_utilization_pct": {"min": 30, "max": 90, "steps": 3},
                    "difficulty_growth_pct_year": {"min": 0, "max": 80, "steps": 3},
                    "cash_interest_rate_pct_year": {"min": 0, "max": 10, "steps": 4},
                    "gpu_rental_usd_per_hr": {"min": 0, "max": 5, "steps": 3},
                    "energy_sell_price_usd_kwh": {"min": 0, "max": 0.2, "steps": 3},
                    "btc_price_at_horizon": {"min": 40000, "max": 150000, "steps": 4},
                }
            )
        self.assertIn(str(DEFAULT_CELL_CAP), str(ctx.exception))

    def test_defaults_fill_min_max_steps(self):
        specs = validate_grid({"btc_price_shift_pct": {"steps": 5}})
        self.assertEqual(specs[0]["key"], "btc_price_shift_pct")
        self.assertEqual(specs[0]["min"], -50.0)
        self.assertEqual(specs[0]["max"], 50.0)
        self.assertEqual(len(specs[0]["values"]), 5)


class TornadoGridTests(unittest.TestCase):
    def test_tornado_cell_count_is_sum_of_steps(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={
                "btc_price_shift_pct": {"min": -25, "max": 25, "steps": 3},
                "electricity_usd_kwh": {"min": 0.03, "max": 0.08, "steps": 2},
            },
            owned={},
        )
        self.assertEqual(out["mode"], "tornado")
        # 3 (btc) + 2 (electricity) == 5 cells, NOT 6 (no joint cross product)
        self.assertEqual(out["cell_count"], 5)

    def test_btc_price_shift_moves_horizon_price_only(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={"btc_price_shift_pct": {"min": -25, "max": 25, "steps": 3}},
            owned={},
        )
        # horizon = 80k * (1 + shift), spot stays 60k
        self.assertEqual(out["cells"][0]["btc_price"], 60_000)
        self.assertAlmostEqual(out["cells"][0]["btc_price_at_horizon"], 60_000)
        self.assertAlmostEqual(out["cells"][2]["btc_price_at_horizon"], 100_000)

    def test_electricity_sweep_is_monotonic_down_for_mining_profit(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={"electricity_usd_kwh": {"min": 0.03, "max": 0.09, "steps": 4}},
            owned={},
        )
        mining_profits = [
            c["lanes"]["mining"]["operating_profit_month"] for c in out["cells"]
        ]
        for i in range(1, len(mining_profits)):
            self.assertGreaterEqual(mining_profits[i - 1], mining_profits[i] + 1e-9)

    def test_uptime_sweep_is_monotonic_up_for_mining_profit(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={"uptime_pct": {"min": 60, "max": 100, "steps": 3}},
            owned={},
        )
        mining_profits = [
            c["lanes"]["mining"]["operating_profit_month"] for c in out["cells"]
        ]
        for i in range(1, len(mining_profits)):
            self.assertGreaterEqual(mining_profits[i], mining_profits[i - 1] - 1e-9)

    def test_breakeven_never_crosses_within_profitable_range(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={"btc_price_shift_pct": {"min": -10, "max": 20, "steps": 5}},
            owned={},
        )
        be = out["breakeven"]["btc_price_shift_pct"]
        self.assertIsNone(be["breakeven_value"])
        self.assertIn("remains profitable", be["note"])

    def test_every_cell_has_identical_lane_shape(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={
                "gpu_rental_usd_per_hr": {"min": 1.0, "max": 4.0, "steps": 3},
                "cash_interest_rate_pct_year": {"min": 0, "max": 10, "steps": 2},
            },
            owned={},
        )
        expected_keys = {
            "available", "operating_profit_month", "revenue_month",
            "profit_per_mw", "horizon_value", "power_mw", "integrity_version",
        }
        for cell in out["cells"]:
            self.assertEqual(set(cell["lanes"]), {"btc", "mining", "gpu", "energy"})
            lane = cell["lanes"]["gpu"]
            self.assertEqual(set(lane) - {"power_mw"}, expected_keys - {"power_mw"})
            self.assertIn("integrity_version", lane)


class JointGridTests(unittest.TestCase):
    def test_joint_cell_count_is_product(self):
        base = _base_run()
        out = run_capital_risk_grid(
            base=base,
            grid={
                "btc_price_shift_pct": {"min": -25, "max": 25, "steps": 3},
                "electricity_usd_kwh": {"min": 0.03, "max": 0.09, "steps": 2},
            },
            joint=True,
            owned={},
        )
        self.assertEqual(out["mode"], "joint")
        self.assertEqual(out["cell_count"], 6)

    def test_joint_raises_on_overflow(self):
        base = _base_run()
        grid = {k: {"steps": 3} for k in (
            "btc_price_shift_pct", "electricity_usd_kwh", "uptime_pct",
            "gpu_utilization_pct", "gpu_rental_usd_per_hr",
            "energy_sell_price_usd_kwh", "cash_interest_rate_pct_year",
            "btc_price_at_horizon", "difficulty_growth_pct_year",
        )}
        with self.assertRaises(ValueError):
            run_capital_risk_grid(base=base, grid=grid, joint=True, owned={})


if __name__ == "__main__":
    unittest.main()
