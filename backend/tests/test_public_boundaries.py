import unittest

from app.api.capital import _proposal_evidence
from app.core.config import Settings
from app.core.redaction import safe_source_reference


class PublicRedactionTests(unittest.TestCase):
    def test_provider_url_credentials_query_and_fragment_are_not_public(self):
        raw = "https://user:pass@example.net/feed/offers?api_key=secret&x=1#debug"
        self.assertEqual(
            safe_source_reference(raw),
            "https://example.net/feed/offers",
        )

    def test_internal_reference_is_preserved(self):
        self.assertEqual(
            safe_source_reference("internal:GPU_CATALOG"),
            "internal:GPU_CATALOG",
        )


class ProductionConfigTests(unittest.TestCase):
    def test_placeholder_secret_is_rejected_in_production(self):
        with self.assertRaises(ValueError):
            Settings(
                ENVIRONMENT="production",
                SECRET_KEY="change-me-to-a-long-random-string-at-least-32-chars",
                MONGODB_URL="mongodb://app:realpassword@mongo:27017/hf_market_engine?authSource=admin",
                CORS_ORIGINS="https://capital.real-domain.test",
            )

    def test_example_cors_origin_is_rejected_in_production(self):
        with self.assertRaises(ValueError):
            Settings(
                ENVIRONMENT="production",
                SECRET_KEY="a_real_random_secret_key_1234567890_ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                MONGODB_URL="mongodb://app:realpassword@mongo:27017/hf_market_engine?authSource=admin",
                CORS_ORIGINS="https://app.example.com",
            )


class ProposalEvidenceTests(unittest.TestCase):
    @staticmethod
    def _lane(label="COMPLETE", score=95):
        return {
            "quality_label": label,
            "quality_score": score,
            "conflict_count": 0,
            "facts_used": [f"fact-{label}"],
        }

    def test_unallocated_weak_lane_does_not_poison_proposal(self):
        recommendation = {
            "proposed_pct": {
                "btc_treasury_pct": 50,
                "bitcoin_mining_pct": 0,
                "gpu_compute_pct": 0,
                "energy_pct": 0,
                "reserve_pct": 50,
            }
        }
        lanes = {
            "btc": self._lane("COMPLETE", 95),
            "mining": self._lane("UNAVAILABLE", 0),
            "gpu": self._lane("UNAVAILABLE", 0),
            "energy": self._lane("UNAVAILABLE", 0),
        }
        block = _proposal_evidence(recommendation, lanes)
        self.assertEqual(block["label"], "EVIDENCE_BACKED")
        self.assertFalse(block["assumption_heavy"])

    def test_allocated_partial_lane_keeps_proposal_assumption_heavy(self):
        recommendation = {
            "proposed_pct": {
                "btc_treasury_pct": 30,
                "bitcoin_mining_pct": 0,
                "gpu_compute_pct": 50,
                "energy_pct": 0,
                "reserve_pct": 20,
            }
        }
        lanes = {
            "btc": self._lane("COMPLETE", 95),
            "mining": self._lane("UNAVAILABLE", 0),
            "gpu": self._lane("PARTIAL", 70),
            "energy": self._lane("UNAVAILABLE", 0),
        }
        block = _proposal_evidence(recommendation, lanes)
        self.assertEqual(block["label"], "ASSUMPTION_HEAVY")
        self.assertIn("gpu", block["assumption_heavy_lanes"])


if __name__ == "__main__":
    unittest.main()
