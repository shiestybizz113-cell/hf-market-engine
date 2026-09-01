"""
Test the core receipt logic without database dependencies.
"""

import uuid
from datetime import UTC, datetime

from app.models.schemas import PaperTradeOut
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
    build_training_extract,
    verify_receipt,
)


def test_paper_trade_receipt_creation():
    """Test creating a receipt for a paper trade without database dependencies."""
    print("Testing paper trade receipt creation logic...")

    # Create a signing key for testing
    signing_key = SigningKey(key_id="test-signing-key-2026")
    print(f"Created signing key: {signing_key.key_id}")

    # Create a mock paper trade (similar to what would come from paper_trading_engine)
    paper_trade = PaperTradeOut(
        id=str(uuid.uuid4()),
        user_id="test-user-123",
        asset="AAPL",
        asset_class="stock",
        direction="long",
        quantity=10,
        entry_price=150.0,
        exit_price=155.0,
        stop_loss=145.0,
        take_profit=160.0,
        unrealized_pnl=0.0,
        realized_pnl=50.0,  # (155-150)*10 = 50
        status="closed",
        notes="Test trade for receipt verification",
        strategy_id=None,
        opened_at=datetime.now(UTC),
        closed_at=datetime.now(UTC),
        ai_review=None
    )

    print(f"Created paper trade: {paper_trade.id}")
    print(f"  Symbol: {paper_trade.asset}")
    print(f"  Direction: {paper_trade.direction}")
    print(f"  Quantity: {paper_trade.quantity}")
    print(f"  Entry: {paper_trade.entry_price}")
    print(f"  Exit: {paper_trade.exit_price}")
    print(f"  P&L: {paper_trade.realized_pnl}")

    # Create the receipt (similar to what PaperTradeReceiptService does)
    receipt = Receipt(
        actor=Actor(
            agent_id=paper_trade.user_id,
            agent_type="paper_trading_agent",
            operator_org_id="hf-market-engine"
        ),
        authority=Authority(
            authority_basis=AuthorityBasis.STANDING_AUTHORITY,
            scope="paper_trade.executed"
        ),
        action=Action(
            action_type=ActionType.TRADE_ORDER,
            domain="hf_market_engine.equities_paper",
            payload={
                "symbol": paper_trade.asset,
                "side": paper_trade.direction,
                "qty": paper_trade.quantity,
                "order_type": "market",
                "entry_price": paper_trade.entry_price,
                "exit_price": paper_trade.exit_price,
                "realized_pnl": paper_trade.realized_pnl
            },
            payload_schema_ref="https://hf-market-engine.dev/schemas/action/trade_order/v1.json"
        ),
        environment_state=EnvironmentState(
            mode=EnvironmentMode.PAPER,
            environment_id="hf-market-engine-phase1"
        ),
        claimed_outcome=ClaimedOutcome(
            outcome_type="fill",
            outcome_payload={
                "fill_price": paper_trade.exit_price or paper_trade.entry_price,
                "filled_qty": paper_trade.quantity,
                "pnl": paper_trade.realized_pnl or 0.0
            }
        ),
        verification=Verification(
            status=VerificationStatus.VERIFIED,
            method="self_attested",
            verified_by="hf-market-engine.paper_trading_engine",
            evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED
        ),
        provenance=Provenance(
            data_owner_org_id="hf-market-engine",
            consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
            retention_policy=RetentionPolicy.PURGE_AFTER_90D,
            training_data_license=TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY,
            pii_present=False
        ),
        opened_at=paper_trade.opened_at,
        closed_at=paper_trade.closed_at
    )

    print(f"Created unsigned receipt: {receipt.receipt_id}")

    # Sign the receipt
    signed_receipt = signing_key.sign_receipt(receipt)
    print(f"Signed receipt: {signed_receipt.receipt_id}")
    print(f"  Signed by: {signed_receipt.integrity.signer_public_key_id}")

    # Verify the receipt using the reference implementation
    key_registry = KeyRegistry()
    key_registry.register(signing_key.key_id, signing_key.public_key)

    is_valid, reason = verify_receipt(signed_receipt, key_registry)
    print(f"Verification result: {is_valid}")
    print(f"Reason: {reason}")

    assert is_valid, f"Receipt verification failed: {reason}"
    assert signed_receipt.action.action_type == "trade_order"
    assert signed_receipt.action.payload.get("symbol") == "AAPL"
    assert signed_receipt.action.payload.get("qty") == 10
    assert signed_receipt.claimed_outcome.outcome_payload.get("pnl") == 50.0

    # Test tamper detection
    print("\nTesting tamper detection...")
    tampered = signed_receipt.model_copy(deep=True)
    tampered.claimed_outcome.outcome_payload["pnl"] = 100.0  # Tamper with P&L

    is_valid_tampered, reason_tampered = verify_receipt(tampered, key_registry)
    print(f"Tampered receipt verification: {is_valid_tampered}")
    print(f"Reason: {reason_tampered}")

    assert not is_valid_tampered, "Tampered receipt should fail verification"
    assert "canonical hash mismatch" in reason_tampered.lower() or "signature" in reason_tampered.lower()

    # Test training extract blocking
    print("\nTesting training extract enforcement...")

    # Allowed path: a receipt licensed for training extract yields a signed
    # extract that references the source receipt as a parent.
    extract = build_training_extract(
        signing_key,
        source_receipt=signed_receipt,
        feature_payload={"symbol": "AAPL", "realized_pnl": 50.0},
        source_scheduled_purge_date="2026-11-12",
    )
    is_valid_extract, reason_extract = verify_receipt(extract, key_registry)
    assert is_valid_extract, f"Training extract verification failed: {reason_extract}"
    assert extract.provenance.training_data_license == TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY
    assert extract.graph_links.parent_receipt_ids == [signed_receipt.receipt_id]

    # Blocked path: a receipt with training_data_license=NONE must refuse.
    receipt_no_license = signed_receipt.model_copy(deep=True)
    receipt_no_license.provenance.training_data_license = TrainingDataLicense.NONE
    signed_receipt_no_license = signing_key.sign_receipt(receipt_no_license)

    try:
        build_training_extract(
            signing_key,
            source_receipt=signed_receipt_no_license,
            feature_payload={"test": "feature"},
            source_scheduled_purge_date="2026-11-12",
        )
        raise AssertionError("Should have raised PermissionError")
    except PermissionError as e:
        print(f"Training extract correctly blocked: {e}")
        assert "training_data_license=NONE" in str(e)
