from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.engines.paper_trading import paper_trading_engine
from app.engines.risk_engine import risk_engine
from app.models.schemas import PaperTradeCreate
from app.services.market_data import market_data_service
from app.services.receipt_service import paper_trade_receipt_service


class PaperTradeReceiptPersistenceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await connect_to_mongo()
        db = get_db()
        await db.paper_trades.delete_many({"user_id": {"$regex": "^receipt-ci-"}})
        await db.receipts.delete_many({"user_id": {"$regex": "^receipt-ci-"}})
        await paper_trade_receipt_service.initialize()

    async def asyncTearDown(self):
        await close_mongo_connection()

    async def test_real_paper_trade_path_persists_and_reverifies_receipt(self):
        user_id = f"receipt-ci-{uuid4()}"
        payload = PaperTradeCreate(
            asset="AAPL",
            quantity=2,
            entry_price=231.47,
            direction="long",
        )

        clear_risk = SimpleNamespace(trade_blocked=False, main_factors=[])
        with (
            patch.object(risk_engine, "score_paper_trade", return_value=clear_risk),
            patch.object(market_data_service, "get_quote", AsyncMock(return_value=None)),
        ):
            opened = await paper_trading_engine.open_trade(user_id, payload)

        db = get_db()
        trade = await db.paper_trades.find_one({"_id": opened.id, "user_id": user_id})
        self.assertIsNotNone(trade)
        self.assertEqual(trade["status"], "open")
        self.assertEqual(trade["receipt_status"], "verified")
        self.assertTrue(trade.get("receipt_id"))

        receipt_id = trade["receipt_id"]
        stored = await db.receipts.find_one({"_id": receipt_id, "user_id": user_id})
        self.assertIsNotNone(stored)
        self.assertEqual(stored["source_trade_id"], opened.id)
        self.assertTrue(stored["independent_verification"]["valid"])

        valid, reason = await paper_trade_receipt_service.verify_persisted_receipt(
            receipt_id,
            user_id=user_id,
        )
        self.assertTrue(valid, reason)

        # The user id is persistence metadata, not part of the signed envelope.
        signed_json = stored["receipt"]
        self.assertNotIn(user_id, str(signed_json))
        self.assertFalse(signed_json["provenance"]["pii_present"])

    async def test_tampered_persisted_receipt_fails_reverification(self):
        user_id = f"receipt-ci-{uuid4()}"
        payload = PaperTradeCreate(
            asset="TSLA",
            quantity=1,
            entry_price=412.10,
            direction="long",
        )

        clear_risk = SimpleNamespace(trade_blocked=False, main_factors=[])
        with (
            patch.object(risk_engine, "score_paper_trade", return_value=clear_risk),
            patch.object(market_data_service, "get_quote", AsyncMock(return_value=None)),
        ):
            opened = await paper_trading_engine.open_trade(user_id, payload)

        db = get_db()
        trade = await db.paper_trades.find_one({"_id": opened.id, "user_id": user_id})
        receipt_id = trade["receipt_id"]
        stored = await db.receipts.find_one({"_id": receipt_id})
        tampered = stored["receipt"]
        tampered["claimed_outcome"]["outcome_payload"]["entry_price"] = 1.00
        await db.receipts.update_one(
            {"_id": receipt_id},
            {"$set": {"receipt": tampered}},
        )

        valid, reason = await paper_trade_receipt_service.verify_persisted_receipt(
            receipt_id,
            user_id=user_id,
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "canonical hash mismatch")
