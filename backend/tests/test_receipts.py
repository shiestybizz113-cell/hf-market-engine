import unittest

from receipts import (
    Action,
    ActionType,
    Actor,
    Authority,
    AuthorityBasis,
    ClaimedOutcome,
    ConsentBasis,
    EnvironmentMode,
    EnvironmentState,
    EvidenceStateLabel,
    Provenance,
    Receipt,
    ReceiptGraph,
    RetentionPolicy,
    SigningKey,
    TrainingDataLicense,
    TrustStatus,
    Verification,
    VerificationStatus,
    build_training_extract,
    verify_receipt,
)


def make_trade(symbol="AAPL", license_=TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY):
    return Receipt(
        actor=Actor(
            agent_id="trader-agent-test",
            agent_type="trading_agent",
            operator_org_id="empire-1",
        ),
        authority=Authority(
            authority_basis=AuthorityBasis.STANDING_AUTHORITY,
            scope="paper_trade.test",
        ),
        action=Action(
            action_type=ActionType.TRADE_ORDER,
            domain="hf_market_engine.paper_trading",
            payload={"symbol": symbol, "side": "buy", "qty": 1},
        ),
        environment_state=EnvironmentState(
            mode=EnvironmentMode.PAPER,
            environment_id="hf-market-engine-test",
        ),
        claimed_outcome=ClaimedOutcome(
            outcome_type="fill",
            outcome_payload={"fill_price": 100.0, "filled_qty": 1},
        ),
        verification=Verification(
            status=VerificationStatus.VERIFIED,
            method="test_execution_service",
            verified_by="hf-market-engine-test",
            evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
        ),
        provenance=Provenance(
            data_owner_org_id="empire-1",
            consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
            retention_policy=RetentionPolicy.PURGE_AFTER_90D,
            training_data_license=license_,
            pii_present=False,
        ),
    )


class ReceiptGraphTests(unittest.TestCase):
    def test_signed_receipt_verifies(self):
        key = SigningKey("test-key")
        signed = key.sign_receipt(make_trade())
        valid, reason = verify_receipt(signed, {key.key_id: key.public_key})
        self.assertTrue(valid, reason)

    def test_tampering_breaks_canonical_hash(self):
        key = SigningKey("test-key")
        signed = key.sign_receipt(make_trade())
        tampered = signed.model_copy(deep=True)
        tampered.claimed_outcome.outcome_payload["fill_price"] = 1.0
        valid, reason = verify_receipt(tampered, {key.key_id: key.public_key})
        self.assertFalse(valid)
        self.assertEqual(reason, "canonical hash mismatch")

    def test_rotation_receipt_chains_outgoing_to_incoming_key(self):
        root = SigningKey("root")
        old = SigningKey("old")
        new = SigningKey("new")
        graph = ReceiptGraph()
        rotation = graph.rotate_key(root, old, new)
        self.assertEqual(rotation.integrity.signer_public_key_id, old.key_id)
        self.assertEqual(graph.key_registry[new.key_id], new.public_key)
        valid, reason = verify_receipt(rotation, graph.key_registry)
        self.assertTrue(valid, reason)

    def test_revocation_disputes_without_mutating_signed_receipt(self):
        root = SigningKey("root")
        old = SigningKey("old")
        graph = ReceiptGraph()
        graph.register_key(root.key_id, root.public_key)
        graph.register_key(old.key_id, old.public_key)
        signed = old.sign_receipt(make_trade())
        graph.add(signed)

        graph.revoke_key(
            root,
            revoked_key_id=old.key_id,
            window_start="2020-01-01T00:00:00+00:00",
            window_end="2030-01-01T00:00:00+00:00",
            reason="suspected_storage_compromise",
        )

        overlay = graph.effective_status(signed.receipt_id)
        self.assertEqual(overlay.status, TrustStatus.DISPUTED)
        valid, reason = verify_receipt(graph.get(signed.receipt_id), graph.key_registry)
        self.assertTrue(valid, reason)

    def test_clean_key_receipt_remains_verified(self):
        root = SigningKey("root")
        old = SigningKey("old")
        clean = SigningKey("clean")
        graph = ReceiptGraph()
        graph.register_key(root.key_id, root.public_key)
        graph.register_key(old.key_id, old.public_key)
        graph.register_key(clean.key_id, clean.public_key)
        old_receipt = old.sign_receipt(make_trade("AAPL"))
        clean_receipt = clean.sign_receipt(make_trade("TSLA"))
        graph.add(old_receipt)
        graph.add(clean_receipt)

        graph.revoke_key(
            root,
            revoked_key_id=old.key_id,
            window_start="2020-01-01T00:00:00+00:00",
            window_end="2030-01-01T00:00:00+00:00",
            reason="suspected_storage_compromise",
        )

        self.assertEqual(
            graph.effective_status(clean_receipt.receipt_id).status,
            TrustStatus.VERIFIED,
        )

    def test_training_extract_links_source_and_is_deidentified(self):
        key = SigningKey("training-key")
        source = key.sign_receipt(make_trade())
        extract = build_training_extract(
            key,
            source,
            {"symbol_bucket": "large_cap_tech", "outcome_class": "filled"},
            source_scheduled_purge_date="2026-11-12",
        )
        self.assertEqual(extract.graph_links.parent_receipt_ids, [source.receipt_id])
        self.assertFalse(extract.provenance.pii_present)

    def test_training_extract_is_blocked_when_license_is_none(self):
        key = SigningKey("training-key")
        source = key.sign_receipt(make_trade(license_=TrainingDataLicense.NONE))
        with self.assertRaises(PermissionError):
            build_training_extract(key, source, {"x": 1})


if __name__ == "__main__":
    unittest.main()
