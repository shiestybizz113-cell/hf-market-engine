"""
Market Data Service — normalized, cached, provenance-stamped quotes.

Thin layer over core.market_providers. Every PriceQuote carries provider,
source, observed_at and freshness so the AI layer (and the user) can always
trace where a number came from. Demo values are only ever used when no real
provider is configured, and they are labeled as such.

Research & simulation only. Not financial advice.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.market_providers import (
    market_providers,
    universe_for,
)
from app.models.schemas import PriceQuote, MarketOverview, AssetClass

_CACHE_TTL = 60


class MarketDataService:
    """Abstraction layer. Swaps demo/provider implementations later."""

    def __init__(self) -> None:
        self._cache: Dict[AssetClass, Tuple[float, Dict[str, PriceQuote]]] = {}

    def _cached_quotes(self, asset_class: AssetClass) -> Optional[Dict[str, PriceQuote]]:
        entry = self._cache.get(asset_class)
        if not entry:
            return None
        ts, quotes = entry
        if (datetime.now(timezone.utc) - ts).total_seconds() > _CACHE_TTL:
            return None
        return quotes

    async def _class_quotes(self, asset_class: AssetClass) -> Dict[str, PriceQuote]:
        cached = self._cached_quotes(asset_class)
        if cached is not None:
            return cached

        symbols = list(universe_for(asset_class).keys())
        now = datetime.now(timezone.utc)
        normalized = await market_providers.get_quotes(symbols, asset_class)

        quotes: Dict[str, PriceQuote] = {}
        for sym in symbols:
            nq = normalized.get(sym)
            if nq is None:
                continue
            quotes[sym] = PriceQuote(
                symbol=nq.symbol,
                name=nq.name,
                price=nq.price,
                asset_class=nq.asset_class,
                change_24h=nq.change_24h,
                change_7d=nq.change_7d,
                change_30d=nq.change_30d,
                volume_24h=nq.volume_24h,
                market_cap=nq.market_cap,
                high_24h=nq.high_24h,
                low_24h=nq.low_24h,
                source=nq.source,
                provider=nq.provider,
                observed_at=nq.observed_at,
                freshness_seconds=int((now - nq.observed_at).total_seconds()),
                last_updated=now,
            )
        # Only cache a non-empty set. Caching a failed/empty fetch would let a
        # transient provider outage self-extend under polling — every retry
        # would re-stamp the cache timestamp with nothing usable.
        if quotes:
            self._cache[asset_class] = (now, quotes)
        return quotes

    async def get_quote(self, symbol: str, asset_class: AssetClass) -> Optional[PriceQuote]:
        symbol = symbol.strip().upper()
        if not symbol:
            return None
        quotes = await self._class_quotes(asset_class)
        if symbol in quotes:
            return quotes[symbol]
        if asset_class == AssetClass.CRYPTO:
            for ticker, meta in universe_for(asset_class).items():
                if (meta.get("id") or "").lower() == symbol.lower():
                    return quotes.get(ticker)
        return None

    async def get_crypto_overview(self) -> MarketOverview:
        quotes = await self._class_quotes(AssetClass.CRYPTO)
        global_data = await market_providers.crypto_global()

        btc = quotes.get("BTC")
        eth = quotes.get("ETH")

        tmc = tv = dom = None
        change = None
        if global_data:
            tmc = global_data.get("total_market_cap", {}).get("usd")
            tv = global_data.get("total_volume", {}).get("usd")
            dom = global_data.get("market_cap_percentage", {}).get("btc")
            change = global_data.get("market_cap_change_percentage_24h_usd")
        elif quotes:
            tmc = sum(q.market_cap for q in quotes.values() if q.market_cap)
            tv = sum(q.volume_24h for q in quotes.values() if q.volume_24h)
            dom = (btc.market_cap / tmc * 100) if btc and btc.market_cap and tmc else None

        regime, confidence = self._classify_regime(change)
        return MarketOverview(
            regime=regime,
            regime_confidence=round(confidence, 1),
            btc=btc,
            eth=eth,
            total_market_cap=tmc,
            total_volume_24h=tv,
            btc_dominance=dom,
            last_updated=datetime.now(timezone.utc),
        )

    def _classify_regime(self, market_change_24h: Optional[float]) -> Tuple[str, float]:
        if market_change_24h is None:
            return "mixed", 45.0
        if market_change_24h > 2.5:
            return "risk-on", 68.0
        if market_change_24h < -2.5:
            return "risk-off", 68.0
        return "mixed", 50.0

    async def get_movers(self, asset_class: AssetClass) -> Dict[str, list]:
        quotes = await self._class_quotes(asset_class)
        items = [
            {
                "symbol": q.symbol,
                "price": q.price,
                "change_24h": q.change_24h or 0.0,
                "provider": q.provider,
                "source": q.source,
            }
            for q in quotes.values()
        ]
        gainers = sorted(items, key=lambda x: x["change_24h"], reverse=True)[:8]
        losers = sorted(items, key=lambda x: x["change_24h"])[:8]
        return {"gainers": gainers, "losers": losers}


market_data_service = MarketDataService()
