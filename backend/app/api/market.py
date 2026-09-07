
from fastapi import APIRouter, HTTPException, Query

from app.core.market_providers import (
    COMMODITY_UNIVERSE,
    CRYPTO_UNIVERSE,
    DEFI_UNIVERSE,
    ETF_UNIVERSE,
    FOREX_UNIVERSE,
    MACRO_UNIVERSE,
    STOCK_UNIVERSE,
)
from app.engines.alpha_scanner import alpha_scanner
from app.engines.correlation_engine import correlation_engine
from app.engines.regime_engine import regime_engine
from app.engines.signal_engine import signal_engine
from app.models.schemas import (
    AlphaScanResult,
    AssetClass,
    CorrelationPair,
    MarketOverview,
    MarketRegime,
    PriceQuote,
    TradeIdea,
)
from app.services.market_data import market_data_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=MarketOverview)
async def market_overview():
    return await market_data_service.get_crypto_overview()


@router.get("/prices", response_model=list[PriceQuote])
async def get_prices(
    symbols: str = Query(..., description="Comma-separated symbols"),
    asset_class: AssetClass = AssetClass.CRYPTO,
):
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    results = []
    for s in syms:
        q = await market_data_service.get_quote(s, asset_class)
        if q:
            results.append(q)
    return results


@router.get("/movers")
async def movers(asset_class: AssetClass = AssetClass.CRYPTO):
    return await market_data_service.get_movers(asset_class)


@router.get("/asset/{symbol}")
async def asset_detail(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO):
    quote = await market_data_service.get_quote(symbol, asset_class)
    if not quote:
        raise HTTPException(status_code=404, detail="Asset not found")
    idea = await signal_engine.generate_trade_idea(quote.symbol, asset_class)
    return {
        "quote": quote,
        "ai_summary": idea.thesis,
        "latest_signal": idea,
        "disclaimer": "Research only, not financial advice.",
    }


@router.get("/signals", response_model=list[TradeIdea])
async def list_signals(limit: int = 10):
    return await signal_engine.generate_sample_signals(limit=limit)


@router.get("/correlations", response_model=list[CorrelationPair])
async def correlations():
    """Cross-asset correlation radar computed from rolling series.

    Demo mode: deterministic seeded series, labelled simulated. Live mode:
    real accumulated observations; pairs with too little history are omitted.
    """
    return await correlation_engine.scan()


@router.get("/regime", response_model=MarketRegime)
async def regime():
    """Cross-asset market regime snapshot (SPY/TLT/DXY/BTC/VIX/XAUUSD)."""
    return await regime_engine.snapshot()


@router.get("/alpha", response_model=AlphaScanResult)
async def alpha(limit: int = Query(20, ge=5, le=100)):
    """Ranked cross-asset alpha scan. Demo mode: no anomaly detection.

    Anomaly detection is intentionally disabled until a live-data phase.
    """
    return await alpha_scanner.scan(limit=limit)


@router.get("/ideas/cross-asset", response_model=list[TradeIdea])
async def cross_asset_ideas(limit: int = Query(5, ge=1, le=10)):
    """Cross-asset trade ideas derived from regime + correlation engines."""
    return await signal_engine.generate_cross_asset_ideas(limit=limit)


@router.get("/universe")
async def universe():
    return {
        "crypto": CRYPTO_UNIVERSE,
        "stocks": STOCK_UNIVERSE,
        "etfs": ETF_UNIVERSE,
        "forex": FOREX_UNIVERSE,
        "commodities": COMMODITY_UNIVERSE,
        "macro": MACRO_UNIVERSE,
        "defi": DEFI_UNIVERSE,
    }
