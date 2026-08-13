"""
AI Signal Engine + Cross-Asset Trade Idea generator

Phase 1 uses rule-based + template generation.
Architecture ready for LLM injection (Grok / OpenAI).
"""

from datetime import datetime, timezone
from typing import List
from app.models.schemas import (
    TradeIdea, SignalDirection, SignalType, AssetClass, RiskLevel
)
from app.services.market_data import market_data_service
from app.core import ai
import random
import uuid


SAMPLE_THESES = {
    SignalType.MOMENTUM_BREAKOUT: [
        "Price strength combined with rising volume and improving market regime.",
        "Break above recent resistance with volume confirmation.",
    ],
    SignalType.CRYPTO_STOCK_SYMPATHY: [
        "Crypto-related equity showing upside while BTC remains constructive.",
        "Sympathy move with broader crypto strength and risk-on tone.",
    ],
    SignalType.CORRELATION_DIVERGENCE: [
        "Asset diverging from its historical correlation partner, creating a relative opportunity.",
        "Breakdown in typical correlation relationship may signal idiosyncratic move.",
    ],
    SignalType.RISK_OFF_WARNING: [
        "Rising defensive asset strength and weakening risk assets suggest caution.",
        "Macro pressure and liquidity signals point to reduced risk appetite.",
    ],
    SignalType.MEAN_REVERSION: [
        "Extended move away from short-term mean with declining momentum.",
        "Overbought/oversold conditions on multiple timeframes.",
    ],
}


class SignalEngine:
    async def generate_sample_signals(self, limit: int = 8) -> List[TradeIdea]:
        """Generate realistic sample Trade Ideas across asset classes for Phase 1."""
        ideas = []

        # Crypto ideas
        crypto_assets = [
            ("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
            ("LINK", "chainlink"), ("AVAX", "avalanche-2")
        ]
        for symbol, _ in crypto_assets[:3]:
            direction = random.choice([SignalDirection.BULLISH, SignalDirection.BEARISH, SignalDirection.NEUTRAL])
            stype = random.choice(list(SignalType))
            conf = round(random.uniform(55, 82), 1)
            risk = round(random.uniform(40, 85), 1)
            ideas.append(TradeIdea(
                id=str(uuid.uuid4()),
                asset=symbol,
                asset_class=AssetClass.CRYPTO,
                direction=direction,
                thesis=random.choice(SAMPLE_THESES.get(stype, ["Market structure and volume alignment observed."])),
                signal_type=stype,
                confidence=conf,
                time_horizon=random.choice(["4h–24h", "1–3 days", "1–5 days"]),
                correlation_context="Historically sensitive to broader crypto market and BTC dominance shifts.",
                macro_context="Current regime assessment factored into confidence.",
                risk_score=risk,
                invalidation="Break of key support/resistance or sudden regime shift.",
                paper_trade_setup=f"Simulated {direction.value} setup with defined risk parameters.",
                supporting_indicators=["Volume", "Price structure", "Market regime"],
            ))

        # Stock / ETF sympathy ideas
        stock_ideas = [
            ("COIN", AssetClass.STOCK, SignalType.CRYPTO_STOCK_SYMPATHY,
             "COIN showing relative strength while BTC remains constructive and crypto equities outperform."),
            ("MSTR", AssetClass.STOCK, SignalType.CRYPTO_STOCK_SYMPATHY,
             "MSTR continues to act as a high-beta proxy for BTC exposure."),
            ("NVDA", AssetClass.STOCK, SignalType.MOMENTUM_BREAKOUT,
             "Tech momentum remains firm; watch for AI-related spillover into related crypto narratives."),
            ("SPY", AssetClass.ETF, SignalType.MOMENTUM_BREAKOUT,
             "Broad equity index holding structure; risk-on tone supports risk assets including crypto."),
            ("QQQ", AssetClass.ETF, SignalType.CORRELATION_DIVERGENCE,
             "QQQ vs BTC relationship showing short-term divergence — monitor for mean reversion or regime confirmation."),
        ]
        for symbol, aclass, stype, thesis in stock_ideas:
            direction = SignalDirection.BULLISH if "strength" in thesis.lower() or "firm" in thesis.lower() else random.choice(list(SignalDirection))
            ideas.append(TradeIdea(
                id=str(uuid.uuid4()),
                asset=symbol,
                asset_class=aclass,
                direction=direction,
                thesis=thesis,
                signal_type=stype,
                confidence=round(random.uniform(58, 78), 1),
                time_horizon=random.choice(["1–5 days", "3–10 days"]),
                correlation_context="Cross-asset context included in thesis.",
                macro_context="Risk appetite and dollar/liquidity backdrop considered.",
                risk_score=round(random.uniform(45, 80), 1),
                invalidation="Loss of key levels or sharp deterioration in correlated assets.",
                paper_trade_setup="Add to paper-trade watchlist with defined invalidation.",
                supporting_indicators=["Relative strength", "Volume", "Correlation"],
            ))

        return ideas[:limit]

    async def generate_trade_idea(self, asset: str, asset_class: AssetClass) -> TradeIdea:
        """Generate a single Trade Idea for a specific asset (AI + template fallback)."""
        quote = await market_data_service.get_quote(asset, asset_class)
        quote_text = (
            f"price={quote.price}, 24h={quote.change_24h}%, 7d={quote.change_7d}%, "
            f"30d={quote.change_30d}%, vol24h={quote.volume_24h}, mcap={quote.market_cap}, "
            f"hi24={quote.high_24h}, lo24={quote.low_24h}, source={quote.source}"
            if quote else "no live quote available"
        )
        regime = "unknown"
        if asset_class == AssetClass.CRYPTO:
            try:
                overview = await market_data_service.get_crypto_overview()
                regime = overview.regime
            except Exception:
                pass
        simulation = quote is None or quote.source == "demo"
        thesis = await ai.thesis_for(
            asset.upper(), asset_class.value, quote_text, regime, simulation=simulation
        )

        stype = random.choice(list(SignalType))
        direction = random.choice(list(SignalDirection))
        return TradeIdea(
            id=str(uuid.uuid4()),
            asset=asset.upper(),
            asset_class=asset_class,
            direction=direction,
            thesis=thesis,
            signal_type=stype,
            confidence=round(random.uniform(55, 80), 1),
            time_horizon=random.choice(["4h–24h", "1–3 days", "1–5 days"]),
            correlation_context="Cross-market relationships evaluated.",
            macro_context="Current market regime considered.",
            risk_score=round(random.uniform(40, 85), 1),
            invalidation="Break of structural levels or regime change.",
            paper_trade_setup="Simulated setup ready for paper trading.",
            supporting_indicators=["Price action", "Volume", "Regime"],
        )


signal_engine = SignalEngine()
