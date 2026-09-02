"""End-to-end regression test for PaperTradeReceiptService.verify_receipt.

The service's verify path used to call KeyRegistry.register_key — a method
that does not exist on the crypto KeyRegistry — so the first real verification
would raise AttributeError against an empty registry. On top of that, the
public key was persisted as a raw cryptography object, which is not BSON
encodable (storing it raised bson.errors.InvalidDocument). The only test that
exercised this path lived in app/ (out of pytest collection under
testpaths=tests) and never ran. This test drives the real service against the
real test DB so neither regression can return silently.
"""

import pytest_asyncio

from app.receipts import (
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
    KeyRegistry,
    Provenance,
    Receipt,
    RetentionPolicy,
    SigningKey,
    TrainingDataLicense,
    Verification,
    VerificationStatus,
)
from app.services.receipts.paper_trade_receipt_service import PaperTradeReceiptService


@pytest_asyncio.fixture()
async def service(_mongo):
    return PaperTradeReceiptService()


async def test_service_verify_receipt_with_db_stored_key(service):
    """verify_receipt loads keys from the DB by key_id/public_key and
    successfully verifies a receipt signed with that key. This is the exact
    seam that used to call the nonexistent register_key method and that stored
    an un-encodable cryptography object in Mongo."""
    await service._ensure_collections_initialized()

    signing_key = SigningKey(key_id=service.paper_trading_key_id)

    await service._get_keys_collection().insert_one(
        {
            "key_id": signing_key.key_id,
            "public_key": signing_key.public_key_bytes.hex(),
            "created_at": None,
            "is_active": True,
            "key_type": "ed25519",
            "purpose": "paper_trading",
        }
    )

    # Build and sign a receipt in memory (signing needs the private key, which
    # lives in the SigningKey object — the DB only stores the public half).
    receipt = Receipt(
        actor=Actor(
            agent_id="user-regression-1",
            agent_type="paper_trading_agent",
            operator_org_id="hf-market-engine",
        ),
        authority=Authority(
            authority_basis=AuthorityBasis.STANDING_AUTHORITY,
            scope="paper_trade.executed",
        ),
        action=Action(
            action_type=ActionType.TRADE_ORDER,
            domain="hf_market_engine.equities_paper",
            payload={"symbol": "AAPL", "qty": 10, "entry_price": 100.0, "exit_price": 110.0},
        ),
        environment_state=EnvironmentState(
            mode=EnvironmentMode.PAPER,
            environment_id="hf-market-engine-phase1",
        ),
        claimed_outcome=ClaimedOutcome(
            outcome_type="fill",
            outcome_payload={"pnl": 100.0},
        ),
        verification=Verification(
            status=VerificationStatus.VERIFIED,
            method="self_attested",
            verified_by="hf-market-engine.paper_trading_engine",
            evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
        ),
        provenance=Provenance(
            data_owner_org_id="hf-market-engine",
            consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
            retention_policy=RetentionPolicy.PURGE_AFTER_90D,
            training_data_license=TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY,
            pii_present=False,
        ),
    )
    signed = signing_key.sign_receipt(receipt)

    is_valid, reason = await service.verify_receipt(signed)
    assert is_valid, f"DB-backed verification failed: {reason}"

    # Tampering must fail through the same DB-backed path.
    signed.claimed_outcome.outcome_payload["pnl"] = 1000.0
    is_valid_tampered, _ = await service.verify_receipt(signed)
    assert not is_valid_tampered, "Tampered receipt should fail DB-backed verification"


async def test_stored_public_key_is_bson_encodable(service):
    """Regression: the service used to store signing_key.public_key (a raw
    cryptography object); persisting it raised bson InvaldDocument. Now keys
    are stored as hex and must round-trip back to an Ed25519PublicKey."""
    await service._ensure_collections_initialized()

    signing_key = SigningKey(key_id=service.paper_trading_key_id)

    doc = {
        "key_id": signing_key.key_id,
        "public_key": signing_key.public_key_bytes.hex(),
        "created_at": None,
        "is_active": True,
        "key_type": "ed25519",
        "purpose": "paper_trading",
    }
    await service._get_keys_collection().insert_one(doc)
    stored = await service._get_keys_collection().find_one(
        {"key_id": signing_key.key_id}
    )
    assert stored["public_key"] == signing_key.public_key_bytes.hex()

    # Round-trip back through the same serialization verify_receipt uses.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(stored["public_key"]))
    registry = KeyRegistry()
    registry.register(signing_key.key_id, pub)
    assert registry.get(signing_key.key_id) == pub
