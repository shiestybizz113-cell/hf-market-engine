from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from app.services.market_data import market_data_service, CRYPTO_UNIVERSE, STOCK_UNIVERSE, ETF_UNIVERSE
from app.models.schemas import PriceQuote, MarketOverview, AssetClass
from app.engines.signal_engine import signal_engine
from app.models.schemas import TradeIdea, CorrelationPair

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=MarketOverview)
async def market_overview():
    return await market_data_service.get_crypto_overview()


@router.get("/prices", response_model=List[PriceQuote])
async def get_prices(
    symbols: str = Query(..., description="Comma-separated symbols"),
    asset_class: AssetClass = AssetClass.CRYPTO,
):
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    results = []
    for s in syms:
        # CoinGecko uses ids for crypto
        lookup = s.lower() if asset_class == AssetClass.CRYPTO else s.upper()
        q = await market_data_service.get_quote(lookup, asset_class)
        if q:
            results.append(q)
    return results


@router.get("/movers")
async def movers(asset_class: AssetClass = AssetClass.CRYPTO):
    return await market_data_service.get_movers(asset_class)


@router.get("/asset/{symbol}")
async def asset_detail(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO):
    lookup = symbol.lower() if asset_class == AssetClass.CRYPTO else symbol.upper()
    quote = await market_data_service.get_quote(lookup, asset_class)
    if not quote:
        raise HTTPException(status_code=404, detail="Asset not found")
    idea = await signal_engine.generate_trade_idea(quote.symbol, asset_class)
    return {
        "quote": quote,
        "ai_summary": idea.thesis,
        "latest_signal": idea,
        "disclaimer": "Research only, not financial advice.",
    }


@router.get("/signals", response_model=List[TradeIdea])
async def list_signals(limit: int = 10):
    return await signal_engine.generate_sample_signals(limit=limit)


@router.get("/correlations", response_model=List[CorrelationPair])
async def correlations():
    """Phase 1 sample correlation radar data."""
    return [
        CorrelationPair(
            pair="BTC / QQQ",
            asset_a="BTC",
            asset_b="QQQ",
            correlation=0.62,
            relationship_type="Risk asset correlation",
            status="Diverging",
            ai_explanation="BTC is holding relative strength while QQQ shows softer momentum, suggesting crypto-specific flows but fragile broader risk appetite.",
            risk_warning="Watch for reversal if tech weakness spreads into crypto.",
        ),
        CorrelationPair(
            pair="BTC / DXY",
            asset_a="BTC",
            asset_b="DXY",
            correlation=-0.48,
            relationship_type="Inverse (dollar strength)",
            status="Aligned",
            ai_explanation="Dollar firmness continues to act as a headwind for risk assets including crypto.",
            risk_warning=None,
        ),
        CorrelationPair(
            pair="COIN / BTC",
            asset_a="COIN",
            asset_b="BTC",
            correlation=0.78,
            relationship_type="Crypto-equity sympathy",
            status="Aligned",
            ai_explanation="COIN remains highly sensitive to BTC direction and crypto market sentiment.",
            risk_warning="High beta — amplified moves in both directions.",
        ),
        CorrelationPair(
            pair="MSTR / BTC",
            asset_a="MSTR",
            asset_b="BTC",
            correlation=0.85,
            relationship_type="High-beta BTC proxy",
            status="Aligned",
            ai_explanation="MSTR continues to trade as a leveraged proxy for Bitcoin exposure.",
            risk_warning="Elevated volatility relative to spot BTC.",
        ),
        CorrelationPair(
            pair="BTC / Gold",
            asset_a="BTC",
            asset_b="XAUUSD",
            correlation=0.15,
            relationship_type="Weak / regime-dependent",
            status="Neutral",
            ai_explanation="Correlation remains low; both can act as alternative stores of value under different macro regimes.",
            risk_warning=None,
        ),
    ]


@router.get("/universe")
async def universe():
    return {
        "crypto": CRYPTO_UNIVERSE,
        "stocks": STOCK_UNIVERSE,
        "etfs": ETF_UNIVERSE,
    }
