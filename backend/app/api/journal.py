from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.core.plans import consume_ai_review
from app.engines.journal_engine import journal_engine

router = APIRouter(prefix="/journal", tags=["journal"])


class JournalCreate(BaseModel):
    asset: str
    direction: str
    entry_price: float
    exit_price: float | None = None
    quantity: float = 0
    pnl: float | None = None
    strategy_id: str | None = None
    notes: str | None = None
    emotion: str | None = None
    mistake_tag: str | None = None
    lesson: str | None = None


class JournalOut(BaseModel):
    id: str
    trade_date: datetime
    asset: str
    direction: str
    entry_price: float
    exit_price: float | None
    quantity: float
    pnl: float | None
    source: str
    notes: str | None
    emotion: str | None
    mistake_tag: str | None
    ai_review: str | None
    lesson: str | None


@router.get("", response_model=list[JournalOut])
async def list_journal(current_user=Depends(get_current_user)):
    entries = await journal_engine.list_entries(current_user["_id"])
    return [
        JournalOut(
            id=e["_id"],
            trade_date=e["trade_date"],
            asset=e["asset"],
            direction=e["direction"],
            entry_price=e["entry_price"],
            exit_price=e.get("exit_price"),
            quantity=e.get("quantity", 0),
            pnl=e.get("pnl"),
            source=e.get("source", "manual"),
            notes=e.get("notes"),
            emotion=e.get("emotion"),
            mistake_tag=e.get("mistake_tag"),
            ai_review=e.get("ai_review"),
            lesson=e.get("lesson"),
        )
        for e in entries
    ]


@router.post("", response_model=JournalOut)
async def create_journal(payload: JournalCreate, current_user=Depends(get_current_user)):
    await consume_ai_review(current_user)
    e = await journal_engine.create_entry(
        current_user["_id"],
        asset=payload.asset,
        direction=payload.direction,
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        quantity=payload.quantity,
        pnl=payload.pnl,
        strategy_id=payload.strategy_id,
        source="manual",
        notes=payload.notes,
        emotion=payload.emotion,
        mistake_tag=payload.mistake_tag,
    )
    if payload.lesson:
        from app.core.database import get_db
        db = get_db()
        await db.journal.update_one({"_id": e["_id"]}, {"$set": {"lesson": payload.lesson}})
        e["lesson"] = payload.lesson
    return JournalOut(
        id=e["_id"],
        trade_date=e["trade_date"],
        asset=e["asset"],
        direction=e["direction"],
        entry_price=e["entry_price"],
        exit_price=e.get("exit_price"),
        quantity=e.get("quantity", 0),
        pnl=e.get("pnl"),
        source=e.get("source", "manual"),
        notes=e.get("notes"),
        emotion=e.get("emotion"),
        mistake_tag=e.get("mistake_tag"),
        ai_review=e.get("ai_review"),
        lesson=e.get("lesson"),
    )
