from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.api.auth import get_current_user
from app.core.plans import consume_ai_review
from app.engines.journal_engine import journal_engine

router = APIRouter(prefix="/journal", tags=["journal"])


class JournalCreate(BaseModel):
    asset: str
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float = 0
    pnl: Optional[float] = None
    strategy_id: Optional[str] = None
    notes: Optional[str] = None
    emotion: Optional[str] = None
    mistake_tag: Optional[str] = None
    lesson: Optional[str] = None


class JournalOut(BaseModel):
    id: str
    trade_date: datetime
    asset: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    pnl: Optional[float]
    source: str
    notes: Optional[str]
    emotion: Optional[str]
    mistake_tag: Optional[str]
    ai_review: Optional[str]
    lesson: Optional[str]


@router.get("", response_model=List[JournalOut])
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
