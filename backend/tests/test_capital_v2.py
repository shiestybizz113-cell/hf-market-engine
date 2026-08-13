import asyncio
import unittest

from app.core import evidence as E
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.evidence_broker import lane_evidence


class EnergyStorageIntegrityTests(unittest.TestCase):
    def _base(self):
        return {
            "lanes": {
                "energy": {
                    "available": True,
                    "power_mw": 0.0,
                    "risk_flags": ["energy_economics_assumed"],
                    "assumptions": {},
                }
            },
            "inputs": {
                "capital_usd": 10_000.0,
                "horizon_months": 12,
                "electricity_usd_kwh": 0.03,
                "energy_acquisition_usd_kwh": 0.03,
                "energy_sell_price_usd_kwh": 0.09,
                "energy_utilization_pct": 100.0,
                "storage_mwh": 1.0,
                "storage_capex_usd_per_mwh": 1_000.0,
                "storage_roundtrip_pct": 85.0,
            },
            "owned": {"summary": {"storage_mwh": 5.0}},
        }

    def test_mwh_to_kwh_and_payback_units_are_correct(self):
        result = apply_energy_storage_integrity(self._base())
        lane = result["lanes"]["energy"]
        unit = lane["per_unit"]

        self.assertAlmostEqual(unit["storage_charge_kwh_day"], 1000.0)
        self.assertAlmostEqual(unit["storage_discharge_kwh_day"], 850.0)
        self.assertAlmostEqual(unit["storage_revenue_day"], 76.5)
        self.assertAlmostEqual(unit["storage_cost_day"], 30.0)
        self.assertAlmostEqual(unit["storage_profit_day"], 46.5)
        self.assertAlmostEqual(lane["simple_payback_days"], 1000.0 / 46.5)
        self.assertEqual(lane["integrity_version"], "energy-storage-v2")

    def test_owned_storage_is_not_rebought(self):
        result = apply_energy_storage_integrity(self._base())
        lane = result["lanes"]["energy"]
        self.assertEqual(lane["capital_allocated"], 1000.0)
        self.assertEqual(lane["assumptions"]["owned_storage_mwh_excluded_from_new_capex"], 5.0)

    def test_new_storage_is_capital_constrained(self):
        result = self._base()
        result["inputs"]["capital_usd"] = 2500.0
        result["inputs"]["storage_mwh"] = 10.0
        apply_energy_storage_integrity(result)
        lane = result["lanes"]["energy"]
        self.assertEqual(lane["capital_allocated"], 2500.0)
        self.assertEqual(lane["assumptions"]["storage_mwh_deployed"], 2.5)
        self.assertIn("storage_capital_constraint_applied", lane["risk_flags"])


class EvidenceQualityTests(unittest.TestCase):
    @staticmethod
    def _resolution(state, quality="COMPLETE", score=95, fact_id="f"):
        return {
            "value": 1.0,
            "fact_id": fact_id,
            "state": state,
            "provider": "test",
            "source_type": "live_api" if state == E.OBSERVED_LIVE else "user_input",
            "source_reference": "test",
            "observed_at": None,
            "age_seconds": 0.0,
            "fresh": True,
            "quality_label": quality,
            "quality_score": score,
            "explicit_user_input": state == E.USER_ASSUMPTION,
            "conflicts": [],
            "candidates": [],
            "stale_candidate_count": 0,
        }

    def test_assumption_prevents_complete_badge(self):
        block = asyncio.run(lane_evidence(
            lane_key="gpu",
            label="GPU",
            resolutions={
                "market_offer": self._resolution(E.OBSERVED_LIVE, fact_id="live"),
                "utilization": self._resolution(E.USER_ASSUMPTION, score=70, fact_id="assumed"),
            },
        ))
        self.assertEqual(block["quality_label"], E.Q_PARTIAL)
        self.assertEqual(block["observed_pct"], 50.0)
        self.assertEqual(block["assumption_pct"], 50.0)

    def test_missing_fact_makes_lane_unavailable(self):
        missing = self._resolution(E.UNAVAILABLE, quality=E.Q_UNAVAILABLE, score=0, fact_id=None)
        block = asyncio.run(lane_evidence(
            lane_key="energy", label="Energy", resolutions={"sell_price": missing},
        ))
        self.assertEqual(block["quality_label"], E.Q_UNAVAILABLE)
        self.assertIn("sell_price", block["facts_missing"])


if __name__ == "__main__":
    unittest.main()
