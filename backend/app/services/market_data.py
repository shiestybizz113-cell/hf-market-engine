"""
Market Data Provider Layer (Phase 1).

- Crypto: live quotes via CoinGecko (with graceful demo fallback)
- Stocks / ETFs / Macro: demo feed (abstraction ready for Polygon,
  Alpaca, Twelve Data, Finnhub)

Research & simulation only. Not financial advice.
"""

import httpx
import random
from datetime import datetime, timezone
from typing import List, Optional, Dict

from app.models.schemas import PriceQuote, MarketOverview, AssetClass

COINGECKO_URL = "https://api.coingecko.com/api/v3"
TIMEOUT = 6.0

# symbol -> (coingecko id, display name, base demo price)
CRYPTO_UNIVERSE: Dict[str, dict] = {
    "BTC": {"id": "bitcoin", "name": "Bitcoin", "price": 61000.0},
    "ETH": {"id": "ethereum", "name": "Ethereum", "price": 3300.0},
    "SOL": {"id": "solana", "name": "Solana", "price": 150.0},
    "LINK": {"id": "chainlink", "name": "Chainlink", "price": 15.5},
    "AVAX": {"id": "avalanche-2", "name": "Avalanche", "price": 32.0},
    "DOGE": {"id": "dogecoin", "name": "Dogecoin", "price": 0.14},
    "XRP": {"id": "ripple", "name": "XRP", "price": 0.55},
    "ADA": {"id": "cardano", "name": "Cardano", "price": 0.48},
    "DOT": {"id": "polkadot", "name": "Polkadot", "price": 6.8},
    "MATIC": {"id": "matic-network", "name": "Polygon", "price": 0.82},
}

STOCK_UNIVERSE: Dict[str, dict] = {
    "COIN": {"name": "Coinbase Global", "price": 230.0},
    "MSTR": {"name": "MicroStrategy", "price": 1450.0},
    "NVDA": {"name": "NVIDIA", "price": 980.0},
    "AAPL": {"name": "Apple", "price": 210.0},
    "MSFT": {"name": "Microsoft", "price": 420.0},
    "TSLA": {"name": "Tesla", "price": 240.0},
    "AMZN": {"name": "Amazon", "price": 185.0},
}

ETF_UNIVERSE: Dict[str, dict] = {
    "SPY": {"name": "SPDR S&P 500 ETF", "price": 540.0},
    "QQQ": {"name": "Invesco QQQ Trust", "price": 470.0},
    "IWM": {"name": "iShares Russell 2000 ETF", "price": 205.0},
    "GLD": {"name": "SPDR Gold Shares", "price": 230.0},
    "TLT": {"name": "iShares 20+ Year Treasury ETF", "price": 95.0},
}

MACRO_UNIVERSE: Dict[str, dict] = {
    "DXY": {"name": "US Dollar Index", "price": 105.5},
    "XAUUSD": {"name": "Gold / USD", "price": 2380.0},
    "US10Y": {"name": "US 10-Year Yield", "price": 4.3},
}

_SYMBOL_TO_ID: Dict[str, str] = {
    sym: meta["id"] for sym, meta in CRYPTO_UNIVERSE.items()
}
_ID_TO_SYMBOL: Dict[str, str] = {v: k for k, v in _SYMBOL_TO_ID.items()}


class MarketDataService:
    """Abstraction layer. Swaps demo/provider implementations later."""

    def __init__(self) -> None:
        self._coin_quotes: Optional[Dict[str, PriceQuote]] = None
        self._last_fetch: Optional[datetime] = None

    # ---------- Crypto (CoinGecko + demo fallback) ----------

    async def _fetch_coingecko(self, ids: List[str]) -> Dict[str, dict]:
        """Fetch coin market data. Returns {coingecko_id: raw}. Empty on failure."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(
                    f"{COINGECKO_URL}/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "ids": ",".join(ids),
                        "price_change_percentage": "24h,7d,30d",
                        "order": "market_cap_desc",
                        "per_page": 100,
                    },
                )
                if r.status_code != 200:
                    return {}
                return {c["id"]: c for c in r.json()}
        except Exception:
            return {}

    async def _fetch_global(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(f"{COINGECKO_URL}/global")
                if r.status_code != 200:
                    return {}
                return r.json().get("data", {})
        except Exception:
            return {}

    async def _crypto_quotes(self) -> Dict[str, PriceQuote]:
        """Live quotes for the whole crypto universe, cached briefly."""
        now = datetime.now(timezone.utc)
        if self._coin_quotes and self._last_fetch and (now - self._last_fetch).seconds < 60:
            return self._coin_quotes

        ids = [m["id"] for m in CRYPTO_UNIVERSE.values()]
        raw = await self._fetch_coingecko(ids)
        quotes: Dict[str, PriceQuote] = {}
        for sym, meta in CRYPTO_UNIVERSE.items():
            coin = raw.get(meta["id"])
            if coin and coin.get("current_price"):
                p = max(coin["current_price"], 0.00000001)
                quotes[sym] = PriceQuote(
                    symbol=sym,
                    name=coin.get("name") or meta["name"],
                    price=p,
                    asset_class=AssetClass.CRYPTO,
                    change_24h=coin.get("price_change_percentage_24h"),
                    change_7d=coin.get("price_change_percentage_7d_in_currency"),
                    change_30d=coin.get("price_change_percentage_30d_in_currency"),
                    volume_24h=coin.get("total_volume"),
                    market_cap=coin.get("market_cap"),
                    high_24h=coin.get("high_24h"),
                    low_24h=coin.get("low_24h"),
                    source="coingecko",
                    last_updated=datetime.now(timezone.utc),
                )
            else:
                quotes[sym] = self._demo_quote(sym, AssetClass.CRYPTO)
        self._coin_quotes = quotes
        self._last_fetch = now
        return quotes

    def _demo_quote(self, symbol: str, asset_class: AssetClass) -> PriceQuote:
        univ = self._universe(asset_class)
        meta = univ.get(symbol.upper()) or {
            "name": symbol.upper(), "price": 100.0,
        }
        drift = random.uniform(-0.035, 0.035)
        price = max(meta["price"] * (1 + drift), 0.00000001)
        return PriceQuote(
            symbol=symbol.upper(),
            name=meta["name"],
            price=round(price, 6 if price < 1 else 2),
            asset_class=asset_class,
            change_24h=round(random.uniform(-6, 8), 2),
            change_7d=round(random.uniform(-12, 14), 2),
            change_30d=round(random.uniform(-25, 30), 2),
            volume_24h=random.uniform(5e7, 5e10),
            market_cap=random.uniform(5e8, 2e12),
            high_24h=round(price * 1.02, 2),
            low_24h=round(price * 0.98, 2),
            source="demo",
            last_updated=datetime.now(timezone.utc),
        )

    def _universe(self, asset_class: AssetClass) -> Dict[str, dict]:
        if asset_class == AssetClass.STOCK:
            return STOCK_UNIVERSE
        if asset_class == AssetClass.ETF:
            return ETF_UNIVERSE
        if asset_class == AssetClass.MACRO:
            return MACRO_UNIVERSE
        return CRYPTO_UNIVERSE

    async def get_quote(self, symbol: str, asset_class: AssetClass) -> Optional[PriceQuote]:
        symbol = symbol.strip().upper()
        if not symbol:
            return None
        if asset_class == AssetClass.CRYPTO:
            quotes = await self._crypto_quotes()
            return quotes.get(symbol) or self._demo_quote(symbol, asset_class)
        return self._demo_quote(symbol, asset_class)

    async def get_crypto_overview(self) -> MarketOverview:
        quotes = await self._crypto_quotes()
        global_data = await self._fetch_global()

        btc = quotes.get("BTC")
        eth = quotes.get("ETH")

        if global_data:
            tmc = global_data.get("total_market_cap", {}).get("usd")
            tv = global_data.get("total_volume", {}).get("usd")
            dom = global_data.get("market_cap_percentage", {}).get("btc")
            change = global_data.get("market_cap_change_percentage_24h_usd")
        else:
            tmc = sum(q.market_cap or 0 for q in quotes.values()) or 2.3e12
            tv = sum(q.volume_24h or 0 for q in quotes.values()) or 9e10
            dom = 52.0
            change = random.uniform(-3, 3)

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

    def _classify_regime(self, market_change_24h: Optional[float]) -> tuple:
        if market_change_24h is None:
            return "mixed", 45.0
        if market_change_24h > 2.5:
            return "risk-on", 68.0
        if market_change_24h < -2.5:
            return "risk-off", 68.0
        return "mixed", 50.0

    async def get_movers(self, asset_class: AssetClass) -> Dict[str, list]:
        if asset_class == AssetClass.CRYPTO:
            quotes = await self._crypto_quotes()
            items = [
                {"symbol": q.symbol, "price": q.price, "change_24h": q.change_24h or 0.0}
                for q in quotes.values()
            ]
        else:
            items = [
                {"symbol": s, "price": self._demo_quote(s, asset_class).price,
                 "change_24h": self._demo_quote(s, asset_class).change_24h or 0.0}
                for s in self._universe(asset_class)
            ]
        gainers = sorted(items, key=lambda x: x["change_24h"], reverse=True)[:8]
        losers = sorted(items, key=lambda x: x["change_24h"])[:8]
        return {"gainers": gainers, "losers": losers}


market_data_service = MarketDataService()
