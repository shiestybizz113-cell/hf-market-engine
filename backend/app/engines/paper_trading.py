"""
Paper Trading Engine – simulated positions only.
No real exchange execution in Phase 1.
Integrated with Receipt Graph for evidence-based audit trail.
"""

import uuid
from datetime import UTC, datetime

from app.core import ai
from app.core.database import get_db
from app.engines.journal_engine import journal_engine
from app.engines.risk_engine import risk_engine
from app.models.schemas import AssetClass, PaperTradeCreate, PaperTradeOut
from app.services.market_data import market_data_service

# Import receipt functionality
from app.services.receipts.paper_trade_receipt_service import paper_trade_receipt_service


class PaperTradingEngine:
    async def open_trade(self, user_id: str, payload: PaperTradeCreate) -> PaperTradeOut:
        # Risk check
        risk = risk_engine.score_paper_trade(payload)
        if risk.trade_blocked:
            raise ValueError(f"Trade blocked by risk engine: {', '.join(risk.main_factors)}")

        # Resolve entry price
        quote = await market_data_service.get_quote(payload.asset, payload.asset_class)
        entry = payload.entry_price or (quote.price if quote else 0.0)
        if entry <= 0:
            raise ValueError("Unable to determine entry price")

        trade = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "asset": payload.asset.upper(),
            "asset_class": payload.asset_class.value,
            "direction": payload.direction,
            "quantity": payload.quantity,
            "entry_price": entry,
            "current_price": entry,
            "exit_price": None,
            "stop_loss": payload.stop_loss,
            "take_profit": payload.take_profit,
            "unrealized_pnl": 0.0,
            "realized_pnl": None,
            "status": "open",
            "notes": payload.notes,
            "strategy_id": payload.strategy_id,
            "opened_at": datetime.now(UTC),
            "closed_at": None,
            "ai_review": None,
        }

        db = get_db()
        await db.paper_trades.insert_one(trade)
        return self._to_out(trade)

    async def close_trade(self, user_id: str, trade_id: str) -> PaperTradeOut:
        db = get_db()
        trade = await db.paper_trades.find_one({"_id": trade_id, "user_id": user_id})
        if not trade:
            raise ValueError("Trade not found")
        if trade["status"] == "closed":
           raise ValueError("Trade already closed")

        quote = await market_data_service.get_quote(
            trade["asset"], AssetClass(trade["asset_class"])
        )
        exit_price = quote.price if quote else trade["entry_price"]

        direction = 1 if trade["direction"] == "long" else -1
        pnl = direction * (exit_price - trade["entry_price"]) * trade["quantity"]

        update = {
            "exit_price": exit_price,
            "current_price": exit_price,
            "realized_pnl": round(pnl, 2),
            "unrealized_pnl": 0.0,
            "status": "closed",
            "closed_at": datetime.now(UTC),
            "ai_review": await self._post_trade_review(user_id, trade, pnl, quote),
        }
        await db.paper_trades.update_one({"_id": trade_id}, {"$set": update})
        trade.update(update)

        # Auto journal entry
        try:
            await journal_engine.auto_from_paper_close(user_id, trade)
        except Exception:
            pass

        # Create and persist receipt for the closed trade
        try:
            paper_trade_out = self._to_out(trade)
            receipt = await paper_trade_receipt_service.create_paper_trade_receipt(
                paper_trade_out,
                user_id
            )
            print(f"Created receipt for paper trade {trade_id}: {receipt.receipt_id}")
        except Exception as e:
            print(f"Warning: Failed to create receipt for paper trade {trade_id}: {e}")
            # Don't fail the trade closure if receipt creation fails

        return self._to_out(trade)

    async def list_trades(self, user_id: str, status: str | None = None) -> list[PaperTradeOut]:
        db = get_db()
        query = {"user_id": user_id}
        if status:
            query["status"] = status
        cursor = db.paper_trades.find(query).sort("opened_at", -1)
        trades = []
        async for t in cursor:
            # Refresh unrealized for open trades
            if t["status"] == "open":
                quote = await market_data_service.get_quote(
                    t["asset"], AssetClass(t["asset_class"])
                )
                if quote:
                    direction = 1 if t["direction"] == "long" else -1
                    t["current_price"] = quote.price
                    t["unrealized_pnl"] = round(
                        direction * (quote.price - t["entry_price"]) * t["quantity"], 2
                    )
            trades.append(self._to_out(t))
        return trades

    async def _post_trade_review(self, user_id: str, trade: dict, pnl: float, quote) -> str:
        simulation = quote is None or quote.source == "demo"
        return await ai.post_trade_review_for(
            trade["asset"],
            trade["direction"],
            pnl,
            user_id=user_id,
            simulation=simulation,
        )

    def _to_out(self, t: dict) -> PaperTradeOut:
        return PaperTradeOut(
            id=t["_id"],
            user_id=t["user_id"],
            asset=t["asset"],
            asset_class=AssetClass(t["asset_class"]),
            direction=t["direction"],
            quantity=t["quantity"],
            entry_price=t["entry_price"],
            current_price=t.get("current_price"),
            exit_price=t.get("exit_price"),
            stop_loss=t.get("stop_loss"),
            take_profit=t.get("take_profit"),
            unrealized_pnl=t.get("unrealized_pnl"),
            realized_pnl=t.get("realized_pnl"),
            status=t["status"],
            notes=t.get("notes"),
            strategy_id=t.get("strategy_id"),
            opened_at=t["opened_at"],
            closed_at=t.get("closed_at"),
            ai_review=t.get("ai_review"),
        )


paper_trading_engine = PaperTradingEngine()
