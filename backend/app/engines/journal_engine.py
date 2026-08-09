"""
Trade Journal Engine — auto-entry from paper trades & execution sims.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from app.core.database import get_db
import uuid


class JournalEngine:
    async def create_entry(
        self,
        user_id: str,
        *,
        asset: str,
        direction: str,
        entry_price: float,
        exit_price: Optional[float] = None,
        quantity: float = 0,
        pnl: Optional[float] = None,
        strategy_id: Optional[str] = None,
        source: str = "manual",  # manual | paper_trade | execution_sim
        source_id: Optional[str] = None,
        notes: Optional[str] = None,
        emotion: Optional[str] = None,
        mistake_tag: Optional[str] = None,
        ai_review: Optional[str] = None,
    ) -> dict:
        db = get_db()
        entry = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "trade_date": datetime.now(timezone.utc),
            "asset": asset.upper(),
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "strategy_id": strategy_id,
            "source": source,
            "source_id": source_id,
            "notes": notes,
            "emotion": emotion,
            "mistake_tag": mistake_tag,
            "ai_review": ai_review or self._default_review(direction, pnl, source),
            "lesson": None,
            "created_at": datetime.now(timezone.utc),
        }
        await db.journal.insert_one(entry)
        return entry

    async def list_entries(self, user_id: str, limit: int = 50) -> List[dict]:
        db = get_db()
        cursor = db.journal.find({"user_id": user_id}).sort("trade_date", -1).limit(limit)
        return [doc async for doc in cursor]

    async def auto_from_paper_close(self, user_id: str, trade: dict) -> dict:
        """Called when a paper trade is closed."""
        return await self.create_entry(
            user_id,
            asset=trade["asset"],
            direction=trade["direction"],
            entry_price=trade["entry_price"],
            exit_price=trade.get("exit_price"),
            quantity=trade["quantity"],
            pnl=trade.get("realized_pnl"),
            strategy_id=trade.get("strategy_id"),
            source="paper_trade",
            source_id=trade.get("_id") or trade.get("id"),
            notes=trade.get("notes"),
            ai_review=trade.get("ai_review"),
        )

    async def auto_from_execution(self, user_id: str, parent: dict) -> dict:
        """Called when an execution sim completes."""
        side = parent.get("side", "buy")
        direction = "long" if side == "buy" else "short"
        return await self.create_entry(
            user_id,
            asset=parent["asset"],
            direction=direction,
            entry_price=parent.get("arrival_price") or 0,
            exit_price=parent.get("avg_fill_price"),
            quantity=parent.get("filled_qty") or parent.get("quantity") or 0,
            pnl=None,  # shortfall is in bps, not $
            source="execution_sim",
            source_id=parent.get("id") or parent.get("_id"),
            notes=f"Algo: {parent.get('algo', {}).get('algo_type', 'n/a')} · "
                  f"Shortfall: {parent.get('implementation_shortfall_bps', 'n/a')} bps",
            ai_review=(
                f"Execution sim completed via {parent.get('algo', {}).get('algo_type', 'algo')}. "
                f"Implementation shortfall {parent.get('implementation_shortfall_bps', 0):.1f} bps. "
                "Review slice timing and participation vs market conditions."
            ),
        )

    def _default_review(self, direction: str, pnl: Optional[float], source: str) -> str:
        if source == "execution_sim":
            return "Execution simulation recorded. Review shortfall and child-order quality."
        if pnl is None:
            return f"Journal entry for {direction} position. Add notes on process adherence."
        result = "profitable" if pnl > 0 else "losing"
        return (
            f"AI Post-Trade: Simulated {direction} closed with a {result} outcome ({pnl:+.2f}). "
            "Tag process mistakes separately from market outcomes."
        )


journal_engine = JournalEngine()
