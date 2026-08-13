"""
Trading API — watchlist, strategies, backtests, paper trading,
portfolio and risk review. All Phase 1 (research + simulation only).
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.core.database import get_db
from app.core.plans import require_feature, max_watchlist_for
from app.models.schemas import (
    AssetClass,
    BacktestRequest,
    BacktestResult,
    HoldingCreate,
    HoldingOut,
    PaperTradeCreate,
    PaperTradeOut,
    RiskReview,
    StrategyCreate,
    StrategyOut,
    WatchlistItemCreate,
    WatchlistItemOut,
)
from app.engines.paper_trading import paper_trading_engine
from app.engines.backtest_engine import backtest_engine
from app.engines.risk_engine import risk_engine
from app.services.market_data import market_data_service

router = APIRouter(tags=["trading"])


# ---------- Watchlist ----------

@router.get("/watchlist", response_model=List[WatchlistItemOut])
async def list_watchlist(current_user=Depends(get_current_user)):
    db = get_db()
    cursor = db.watchlist.find({"user_id": current_user["_id"]}).sort("added_at", -1)
    items = [doc async for doc in cursor]
    out = []
    for item in items:
        symbol = item["symbol"]
        asset_class = AssetClass(item["asset_class"])
        quote = await market_data_service.get_quote(symbol, asset_class)
        out.append(WatchlistItemOut(
            id=item["_id"],
            symbol=symbol,
            asset_class=asset_class,
            price=quote.price if quote else None,
            change_24h=quote.change_24h if quote else None,
            change_7d=quote.change_7d if quote else None,
            volume=quote.volume_24h if quote else None,
            added_at=item["added_at"],
        ))
    return out


@router.post("/watchlist", response_model=WatchlistItemOut)
async def add_watchlist(payload: WatchlistItemCreate, current_user=Depends(get_current_user)):
    db = get_db()
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(400, "Symbol required")

    plan = current_user.get("plan", "free")
    limit = max_watchlist_for(plan)
    count = await db.watchlist.count_documents({"user_id": current_user["_id"]})
    if count >= limit:
        raise HTTPException(
            400,
            f"{plan.capitalize()} plan allows up to {limit} watchlist items — "
            "upgrade to Pro for more.",
        )

    existing = await db.watchlist.find_one({
        "user_id": current_user["_id"], "symbol": symbol, "asset_class": payload.asset_class.value,
    })
    if existing:
        raise HTTPException(400, "Symbol already in watchlist")

    item = {
        "_id": str(uuid.uuid4()),
        "user_id": current_user["_id"],
        "symbol": symbol,
        "asset_class": payload.asset_class.value,
        "added_at": datetime.now(timezone.utc),
    }
    await db.watchlist.insert_one(item)

    quote = await market_data_service.get_quote(symbol, payload.asset_class)
    return WatchlistItemOut(
        id=item["_id"],
        symbol=symbol,
        asset_class=payload.asset_class,
        price=quote.price if quote else None,
        change_24h=quote.change_24h if quote else None,
        change_7d=quote.change_7d if quote else None,
        volume=quote.volume_24h if quote else None,
        added_at=item["added_at"],
    )


@router.delete("/watchlist/{item_id}")
async def remove_watchlist(item_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    res = await db.watchlist.delete_one({"_id": item_id, "user_id": current_user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Watchlist item not found")
    return {"status": "removed"}


# ---------- Strategies ----------

@router.get("/strategies", response_model=List[StrategyOut])
async def list_strategies(current_user=Depends(require_feature("strategy_lab"))):
    db = get_db()
    cursor = db.strategies.find({"user_id": current_user["_id"]}).sort("created_at", -1)
    return [_strategy_out(doc) async for doc in cursor]


@router.post("/strategies", response_model=StrategyOut)
async def create_strategy(payload: StrategyCreate, current_user=Depends(require_feature("strategy_lab"))):
    db = get_db()
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": current_user["_id"],
        "name": payload.name,
        "asset": payload.asset.upper(),
        "asset_class": payload.asset_class.value,
        "timeframe": payload.timeframe,
        "entry_condition": payload.entry_condition,
        "exit_condition": payload.exit_condition,
        "stop_loss_pct": payload.stop_loss_pct,
        "take_profit_pct": payload.take_profit_pct,
        "max_position_pct": payload.max_position_pct,
        "max_daily_loss_pct": payload.max_daily_loss_pct,
        "market_regime_filter": payload.market_regime_filter,
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc),
    }
    await db.strategies.insert_one(doc)
    return _strategy_out(doc)


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str, current_user=Depends(require_feature("strategy_lab"))):
    db = get_db()
    res = await db.strategies.delete_one({"_id": strategy_id, "user_id": current_user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Strategy not found")
    return {"status": "removed"}


def _strategy_out(doc: dict) -> StrategyOut:
    return StrategyOut(
        id=doc["_id"],
        user_id=doc["user_id"],
        name=doc["name"],
        asset=doc["asset"],
        asset_class=AssetClass(doc["asset_class"]),
        timeframe=doc["timeframe"],
        entry_condition=doc.get("entry_condition"),
        exit_condition=doc.get("exit_condition"),
        stop_loss_pct=doc.get("stop_loss_pct", 2.5),
        take_profit_pct=doc.get("take_profit_pct", 6.0),
        max_position_pct=doc.get("max_position_pct", 5.0),
        max_daily_loss_pct=doc.get("max_daily_loss_pct", 3.0),
        market_regime_filter=doc.get("market_regime_filter", False),
        notes=doc.get("notes"),
        created_at=doc["created_at"],
    )


# ---------- Backtesting ----------

@router.post("/backtests", response_model=BacktestResult)
async def run_backtest(payload: BacktestRequest, current_user=Depends(require_feature("backtesting"))):
    return await backtest_engine.run(payload, user_id=current_user["_id"])


# ---------- Paper Trading ----------

@router.get("/paper-trades", response_model=List[PaperTradeOut])
async def list_paper_trades(status: Optional[str] = None, current_user=Depends(require_feature("paper_trading"))):
    return await paper_trading_engine.list_trades(current_user["_id"], status)


@router.post("/paper-trades", response_model=PaperTradeOut)
async def open_paper_trade(payload: PaperTradeCreate, current_user=Depends(require_feature("paper_trading"))):
    try:
        return await paper_trading_engine.open_trade(current_user["_id"], payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/paper-trades/{trade_id}/close", response_model=PaperTradeOut)
async def close_paper_trade(trade_id: str, current_user=Depends(require_feature("paper_trading"))):
    try:
        return await paper_trading_engine.close_trade(current_user["_id"], trade_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- Portfolio ----------

@router.get("/portfolio", response_model=List[HoldingOut])
async def list_portfolio(current_user=Depends(get_current_user)):
    db = get_db()
    cursor = db.portfolio.find({"user_id": current_user["_id"]}).sort("created_at", -1)
    holdings = [doc async for doc in cursor]

    total_value = 0.0
    enriched = []
    for h in holdings:
        asset_class = AssetClass(h["asset_class"])
        quote = await market_data_service.get_quote(h["asset"], asset_class)
        current_price = quote.price if quote else h["entry_price"]
        current_value = current_price * h["quantity"]
        total_value += current_value
        enriched.append((h, current_price, current_value))

    out = []
    for h, current_price, current_value in enriched:
        entry_value = h["entry_price"] * h["quantity"]
        pnl = current_value - entry_value
        pnl_pct = (pnl / entry_value * 100) if entry_value > 0 else 0.0
        alloc = (current_value / total_value * 100) if total_value > 0 else 0.0
        out.append(HoldingOut(
            id=h["_id"],
            user_id=h["user_id"],
            asset=h["asset"],
            asset_class=AssetClass(h["asset_class"]),
            quantity=h["quantity"],
            entry_price=h["entry_price"],
            current_price=round(current_price, 6),
            current_value=round(current_value, 2),
            unrealized_pnl=round(pnl, 2),
            unrealized_pnl_pct=round(pnl_pct, 2),
            allocation_pct=round(alloc, 1),
            notes=h.get("notes"),
            created_at=h["created_at"],
        ))
    return out


@router.post("/portfolio", response_model=HoldingOut)
async def add_holding(payload: HoldingCreate, current_user=Depends(get_current_user)):
    db = get_db()
    holding = {
        "_id": str(uuid.uuid4()),
        "user_id": current_user["_id"],
        "asset": payload.asset.upper(),
        "asset_class": payload.asset_class.value,
        "quantity": payload.quantity,
        "entry_price": payload.entry_price,
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc),
    }
    await db.portfolio.insert_one(holding)
    return HoldingOut(
        id=holding["_id"],
        user_id=holding["user_id"],
        asset=holding["asset"],
        asset_class=payload.asset_class,
        quantity=holding["quantity"],
        entry_price=holding["entry_price"],
        current_price=holding["entry_price"],
        current_value=round(holding["quantity"] * holding["entry_price"], 2),
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        allocation_pct=100.0,
        notes=holding.get("notes"),
        created_at=holding["created_at"],
    )


# ---------- Risk Review ----------

@router.post("/risk-review/strategy", response_model=RiskReview)
async def risk_review_strategy(payload: StrategyCreate, current_user=Depends(require_feature("risk_engine"))):
    return risk_engine.score_strategy(payload)


@router.post("/risk-review/paper-trade", response_model=RiskReview)
async def risk_review_paper(payload: PaperTradeCreate, current_user=Depends(require_feature("risk_engine"))):
    return risk_engine.score_paper_trade(payload)
