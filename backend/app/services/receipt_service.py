from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import uuid4

from app.core.database import get_db
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
    RetentionPolicy,
    SigningKey,
    TrainingDataLicense,
    Verification,
    VerificationStatus,
    verify_receipt,
)


class ReceiptPersistenceError(RuntimeError):
    pass


class PaperTradeReceiptService:
    """Additive Receipt v1.1 integration for Phase-1 paper trades only."""

    def __init__(self) -> None:
        self._signing_key: Optional[SigningKey] = None

    async def initialize(self) -> None:
        """Create or load the process signing key and persist its public half.

        Paper mode may use an in-process ephemeral key. A configured private key
        must provide a stable key id. Live-stakes execution is intentionally out
        of scope until private-key custody moves to KMS/HSM.
        """
        key_id = os.getenv("RECEIPT_SIGNING_KEY_ID")
        private_key_b64 = os.getenv("RECEIPT_SIGNING_PRIVATE_KEY_B64")

        if private_key_b64 and not key_id:
            raise RuntimeError(
                "RECEIPT_SIGNING_KEY_ID is required when "
                "RECEIPT_SIGNING_PRIVATE_KEY_B64 is configured."
            )

        if private_key_b64:
            signing_key = SigningKey(key_id=key_id, private_key_b64=private_key_b64)
        else:
            suffix = uuid4().hex[:10]
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            signing_key = SigningKey(key_id=f"empire-1-hf-paper-{day}-{suffix}")

        db = get_db()
        existing = await db.receipt_keys.find_one({"_id": signing_key.key_id})
        if existing and existing.get("public_key") != signing_key.public_key:
            raise RuntimeError(
                f"Receipt signing key id {signing_key.key_id} already exists with "
                "different public-key material. Refusing ambiguous key history."
            )

        await db.receipt_keys.update_one(
            {"_id": signing_key.key_id},
            {
                "$setOnInsert": {
                    "public_key": signing_key.public_key,
                    "algorithm": "Ed25519",
                    "created_at": datetime.now(timezone.utc),
                    "environment_mode": "paper",
                }
            },
            upsert=True,
        )
        self._signing_key = signing_key

    def build_paper_trade_receipt(self, user_id: str, trade: dict) -> Receipt:
        if self._signing_key is None:
            raise RuntimeError("Receipt signing service has not been initialized.")

        receipt = Receipt(
            actor=Actor(
                agent_id="hf-market-engine.paper-trading-engine",
                agent_type="trading_engine",
                operator_org_id="empire-1",
            ),
            authority=Authority(
                authority_basis=AuthorityBasis.STANDING_AUTHORITY,
                scope="paper_trade.phase1.user_authorized",
            ),
            action=Action(
                action_type=ActionType.TRADE_ORDER,
                domain="hf_market_engine.paper_trading",
                payload={
                    "trade_id": trade["_id"],
                    "asset": trade["asset"],
                    "asset_class": trade["asset_class"],
                    "direction": trade["direction"],
                    "quantity": trade["quantity"],
                    "order_type": "paper_position_open",
                },
                payload_schema_ref="hf-market-engine://paper-trade/v1",
            ),
            environment_state=EnvironmentState(
                mode=EnvironmentMode.PAPER,
                environment_id="hf-market-engine-phase1",
            ),
            claimed_outcome=ClaimedOutcome(
                outcome_type="paper_position_opened",
                outcome_payload={
                    "trade_id": trade["_id"],
                    "entry_price": trade["entry_price"],
                    "status": trade["status"],
                    "opened_at": trade["opened_at"].isoformat(),
                },
            ),
            verification=Verification(
                status=VerificationStatus.VERIFIED,
                method="paper_trade_persisted_by_execution_service",
                verified_by="hf-market-engine.paper-trading-engine",
                evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
            ),
            provenance=Provenance(
                data_owner_org_id="empire-1",
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.PURGE_AFTER_90D,
                training_data_license=TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY,
                pii_present=False,
            ),
        )
        return self._signing_key.sign_receipt(receipt)

    async def persist_and_verify(
        self,
        signed: Receipt,
        *,
        user_id: str,
        source_trade_id: str,
    ) -> str:
        if signed.integrity is None:
            raise ReceiptPersistenceError("Refusing to persist an unsigned receipt.")

        db = get_db()
        doc = {
            "_id": signed.receipt_id,
            "receipt_id": signed.receipt_id,
            "user_id": user_id,
            "source_type": "paper_trade",
            "source_trade_id": source_trade_id,
            "signer_key_id": signed.integrity.signer_public_key_id,
            "created_at": signed.created_at,
            "receipt": signed.model_dump(mode="json"),
            "independent_verification": {
                "checked": False,
                "valid": None,
                "reason": None,
                "checked_at": None,
            },
        }

        try:
            await db.receipts.insert_one(doc)
        except Exception as exc:
            raise ReceiptPersistenceError(f"Receipt persistence failed: {exc}") from exc

        valid, reason = await self.verify_persisted_receipt(signed.receipt_id, user_id=user_id)
        await db.receipts.update_one(
            {"_id": signed.receipt_id},
            {
                "$set": {
                    "independent_verification": {
                        "checked": True,
                        "valid": valid,
                        "reason": reason,
                        "checked_at": datetime.now(timezone.utc),
                    }
                }
            },
        )

        if not valid:
            raise ReceiptPersistenceError(
                f"Persisted receipt failed independent verification: {reason}"
            )
        return signed.receipt_id

    async def verify_persisted_receipt(
        self,
        receipt_id: str,
        *,
        user_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        db = get_db()
        query = {"_id": receipt_id}
        if user_id is not None:
            query["user_id"] = user_id

        stored = await db.receipts.find_one(query)
        if not stored:
            return False, "receipt not found"

        try:
            receipt = Receipt.model_validate(stored["receipt"])
        except Exception as exc:
            return False, f"stored receipt schema validation failed: {exc}"

        if receipt.integrity is None:
            return False, "stored receipt has no integrity envelope"

        key_doc = await db.receipt_keys.find_one(
            {"_id": receipt.integrity.signer_public_key_id}
        )
        if not key_doc:
            return False, "signer public key not found in durable key registry"

        return verify_receipt(
            receipt,
            {receipt.integrity.signer_public_key_id: key_doc["public_key"]},
        )


paper_trade_receipt_service = PaperTradeReceiptService()
