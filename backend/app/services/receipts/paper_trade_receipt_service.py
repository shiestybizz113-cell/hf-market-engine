"""
Paper Trade Receipt Service
Handles creation and storage of receipts for paper trades.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.database import get_db
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
    verify_receipt,
)


class PaperTradeReceiptService:
    def __init__(self):
        # Initialize or load signing keys for paper trading
        self.paper_trading_key_id = "hf-market-engine-paper-trading-key-2026"
        # Initialize collections will be done async when needed
        self._collections_initialized = False

    def _get_receipts_collection(self):
        """Get the trade_receipts collection from the current database connection."""
        return get_db().trade_receipts

    def _get_keys_collection(self):
        """Get the signing_keys collection from the current database connection."""
        return get_db().signing_keys

    async def _ensure_collections_initialized(self):
        """Initialize database collections with proper indexes if not already done."""
        if self._collections_initialized:
            return

        db = get_db()

        # Create trade_receipts collection if it doesn't exist
        collections = await db.list_collection_names()
        if "trade_receipts" not in collections:
            await db.create_collection("trade_receipts")
            await self._get_receipts_collection().create_index("receipt_id", unique=True)
            await self._get_receipts_collection().create_index("action.action_type")
            await self._get_receipts_collection().create_index("actor.agent_id")
            await self._get_receipts_collection().create_index("integrity.signer_public_key_id")
            await self._get_receipts_collection().create_index("opened_at")

        # Create signing_keys collection if it doesn't exist
        if "signing_keys" not in collections:
            await db.create_collection("signing_keys")
            await self._get_keys_collection().create_index("key_id", unique=True)

        self._collections_initialized = True

    async def _ensure_paper_trading_key(self):
        """Ensure the paper trading signing key exists in the registry."""
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        # Check if key already exists
        existing_key = await self._get_keys_collection().find_one({"key_id": self.paper_trading_key_id})

        if not existing_key:
            # Generate a new Ed25519 key for paper trading
            signing_key = SigningKey(key_id=self.paper_trading_key_id)

            # Store the key in the database
            key_doc = {
                "key_id": signing_key.key_id,
                "public_key": signing_key.public_key,
                "created_at": datetime.now(UTC),
                "is_active": True,
                "key_type": "ed25519",
                "purpose": "paper_trading"
            }

            await self._get_keys_collection().insert_one(key_doc)
            print(f"Created new paper trading signing key: {self.paper_trading_key_id}")
        else:
            print(f"Using existing paper trading signing key: {self.paper_trading_key_id}")

    async def _load_signing_key(self) -> SigningKey:
        """Load the signing key from database."""
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        key_doc = await self._get_keys_collection().find_one({"key_id": self.paper_trading_key_id})
        if key_doc:
            return SigningKey(
                key_id=key_doc["key_id"],
                public_key=key_doc["public_key"]
            )
        else:
            # Key doesn't exist, create and store it
            signing_key = SigningKey(key_id=self.paper_trading_key_id)

            # Store the key in the database
            key_doc = {
                "key_id": signing_key.key_id,
                "public_key": signing_key.public_key,
                "created_at": datetime.now(UTC),
                "is_active": True,
                "key_type": "ed25519",
                "purpose": "paper_trading"
            }

            await self._get_keys_collection().insert_one(key_doc)
            print(f"Created and stored new paper trading signing key: {self.paper_trading_key_id}")

            return signing_key

    async def create_paper_trade_receipt(
        self,
        paper_trade: PaperTradeOut,
        user_id: str,
        operator_org_id: str = "hf-market-engine"
    ) -> Receipt:
        """
        Create a signed receipt for a completed paper trade.

        Args:
            paper_trade: The completed paper trade
            user_id: ID of the user who made the trade
            operator_org_id: Organization that operates the trading system

        Returns:
            Signed Receipt object
        """
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        # Load signing key
        signing_key = await self._load_signing_key()

        # Create the receipt
        receipt = Receipt(
            actor=Actor(
                agent_id=user_id,
                agent_type="paper_trading_agent",
                operator_org_id=operator_org_id
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
                    "realized_pnl": paper_trade.realized_pnl,
                    "trade_id": str(paper_trade.id)  # Store trade ID for querying
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
                data_owner_org_id=operator_org_id,
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.PURGE_AFTER_90D,
                training_data_license=TrainingDataLicense.LICENSABLE_AGGREGATE_ONLY,
                pii_present=False
            )
        )

        # Sign the receipt
        signed_receipt = signing_key.sign_receipt(receipt)

        # Persist the receipt to database
        receipt_doc = self._receipt_to_document(signed_receipt)
        await self._get_receipts_collection().insert_one(receipt_doc)

        # Also store a copy to file system for durability (as requested)
        self._persist_receipt_to_file(signed_receipt)

        return signed_receipt

    def _receipt_to_document(self, receipt: Receipt) -> dict:
        """Convert Receipt object to MongoDB document."""
        # Convert to JSON and back to get a clean dict
        json_str = receipt.model_dump_json()
        doc = json.loads(json_str)

        # Add MongoDB-specific fields
        doc["_id"] = str(receipt.receipt_id)  # Use receipt_id as _id for convenience
        doc["created_at"] = datetime.now(UTC)
        return doc

    def _persist_receipt_to_file(self, receipt: Receipt) -> None:
        """Persist a copy of the receipt to the file system for durability."""
        # Create storage directory if it doesn't exist
        storage_dir = Path("/home/shiestybizz113/projects/hf-market-engine/backend/app/receipts/storage")
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Create filename based on receipt ID and timestamp
        filename = f"{receipt.receipt_id}.json"
        filepath = storage_dir / filename

        # Write receipt as JSON
        with open(filepath, 'w') as f:
            # Convert to dict and handle datetime serialization
            receipt_dict = receipt.dict()
            # Convert datetime objects to ISO format strings
            for key, value in receipt_dict.items():
                if isinstance(value, datetime):
                    receipt_dict[key] = value.isoformat()
            json.dump(receipt_dict, f, indent=2)

    async def get_receipt_by_id(self, receipt_id: str) -> Receipt | None:
        """
        Retrieve a receipt by its ID.

        Args:
            receipt_id: The ID of the receipt to retrieve

        Returns:
            Receipt object if found, None otherwise
        """
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        receipt_doc = await self._get_receipts_collection().find_one({"_id": receipt_id})
        if receipt_doc:
            # Remove MongoDB-specific fields
            receipt_doc.pop("_id", None)
            receipt_doc.pop("created_at", None)
            return Receipt(**receipt_doc)
        return None

    async def get_receipts_for_trade(self, trade_id: str) -> list[Receipt]:
        """
        Get all receipts associated with a specific trade.

        Args:
            trade_id: The ID of the trade

        Returns:
            List of Receipt objects
        """
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        # Find receipts where the action.payload contains the trade_id
        receipts = []
        async for doc in self._get_receipts_collection().find({"action.payload.trade_id": trade_id}):
            # Remove MongoDB-specific fields
            doc.pop("_id", None)
            doc.pop("created_at", None)
            try:
                receipt = Receipt(**doc)
                receipts.append(receipt)
            except Exception:
                # Skip invalid receipt documents
                continue
        return receipts

    async def get_receipts_for_user(self, user_id: str, limit: int = 50) -> list[Receipt]:
        """Get receipts for a specific user."""
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        cursor = self._get_receipts_collection().find(
            {"actor.agent_id": user_id}
        ).sort("opened_at", -1).limit(limit)

        receipts = []
        async for doc in cursor:
            # Remove MongoDB-specific fields
            doc.pop("_id", None)
            doc.pop("created_at", None)
            receipts.append(Receipt(**doc))

        return receipts

    async def verify_receipt(self, receipt: Receipt) -> tuple[bool, str]:
        """
        Verify a receipt's signature and integrity.

        Returns:
            Tuple of (is_valid, reason)
        """
        # Ensure collections are initialized
        await self._ensure_collections_initialized()

        # Load public keys from database
        key_registry = KeyRegistry()

        # Get all active signing keys from database
        keys_cursor = self._get_keys_collection().find({"is_active": True})
        async for key_doc in keys_cursor:
            key_registry.register(
                key_doc["key_id"],
                key_doc["public_key"]
            )

        # Verify the receipt
        return verify_receipt(receipt, key_registry)


# Global service instance
paper_trade_receipt_service = PaperTradeReceiptService()
