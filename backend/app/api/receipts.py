from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.core.database import get_db
from app.services.receipt_service import paper_trade_receipt_service

router = APIRouter(tags=["receipts"])


@router.get("/receipts/by-trade/{trade_id}")
async def receipt_for_paper_trade(
    trade_id: str,
    current_user=Depends(get_current_user),
):
    """Return the user's durable Receipt v1.1 envelope for one paper trade."""
    db = get_db()
    trade = await db.paper_trades.find_one(
        {"_id": trade_id, "user_id": current_user["_id"]}
    )
    if not trade:
        raise HTTPException(404, "Paper trade not found")

    receipt_id = trade.get("receipt_id")
    if not receipt_id:
        raise HTTPException(404, "No Receipt v1.1 is attached to this paper trade")

    stored = await db.receipts.find_one(
        {"_id": receipt_id, "user_id": current_user["_id"]}
    )
    if not stored:
        raise HTTPException(409, "Paper trade references a receipt that is not durable")

    return {
        "trade_id": trade_id,
        "receipt_id": receipt_id,
        "receipt_status": trade.get("receipt_status"),
        "receipt": stored["receipt"],
        "independent_verification": stored.get("independent_verification"),
    }


@router.get("/receipts/{receipt_id}/verify")
async def verify_persisted_receipt(
    receipt_id: str,
    current_user=Depends(get_current_user),
):
    """Re-read one persisted receipt and cryptographically verify it now."""
    db = get_db()
    stored = await db.receipts.find_one(
        {"_id": receipt_id, "user_id": current_user["_id"]}
    )
    if not stored:
        raise HTTPException(404, "Receipt not found")

    valid, reason = await paper_trade_receipt_service.verify_persisted_receipt(
        receipt_id,
        user_id=current_user["_id"],
    )
    return {
        "receipt_id": receipt_id,
        "valid": valid,
        "reason": reason,
        "signer_key_id": stored.get("signer_key_id"),
        "source_trade_id": stored.get("source_trade_id"),
    }
