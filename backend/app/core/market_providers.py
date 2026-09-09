"""
Market data provider layer — one normalized interface, honest provenance.

Every quote is stamped with its provider, source and observation time so the
AI layer (and the user) always knows where the number came from. Providers
never fabricate data: if a symbol cannot be fetched it is simply omitted, and
callers decide how to label the gap.

Honesty contract (see settings.MARKET_DATA_MODE):
  live : real providers only (coingecko, twelvedata). If a real provider is
         down or unconfigured, missing data stays missing — demo never fills in.
  demo : DemoProvider only; every quote is labeled source="demo".
         Forcing demo over live (e.g. temporary override) is possible but the
         label is always preserved so no synthetic value ever masquerades as
         live truth.
"""

import hashlib
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.models.schemas import AssetClass

COINGECKO_URL = "https://api.coingecko.com/api/v3"
TWELVEDATA_URL = "https://api.twelvedata.com"
PROVIDER_TIMEOUT = 8.0

# symbol -> (coingecko id, display name, base demo price)
CRYPTO_UNIVERSE: dict[str, dict] = {
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

STOCK_UNIVERSE: dict[str, dict] = {
    "COIN": {"name": "Coinbase Global", "price": 230.0},
    "MSTR": {"name": "MicroStrategy", "price": 1450.0},
    "NVDA": {"name": "NVIDIA", "price": 980.0},
    "AAPL": {"name": "Apple", "price": 210.0},
    "MSFT": {"name": "Microsoft", "price": 420.0},
    "TSLA": {"name": "Tesla", "price": 240.0},
    "AMZN": {"name": "Amazon", "price": 185.0},
    "GOOGL": {"name": "Alphabet", "price": 175.0},
    "META": {"name": "Meta Platforms", "price": 500.0},
    "NFLX": {"name": "Netflix", "price": 640.0},
    "AMD": {"name": "Advanced Micro Devices", "price": 160.0},
    "PLTR": {"name": "Palantir Technologies", "price": 25.0},
    "SQ": {"name": "Block", "price": 65.0},
    "HOOD": {"name": "Robinhood Markets", "price": 20.0},
}

ETF_UNIVERSE: dict[str, dict] = {
    "SPY": {"name": "SPDR S&P 500 ETF", "price": 540.0},
    "QQQ": {"name": "Invesco QQQ Trust", "price": 470.0},
    "IWM": {"name": "iShares Russell 2000 ETF", "price": 205.0},
    "GLD": {"name": "SPDR Gold Shares", "price": 230.0},
    "TLT": {"name": "iShares 20+ Year Treasury ETF", "price": 95.0},
    "ARKK": {"name": "ARK Innovation ETF", "price": 55.0},
    "VTI": {"name": "Vanguard Total Stock Market ETF", "price": 260.0},
    "EEM": {"name": "iShares MSCI Emerging Markets ETF", "price": 42.0},
}

FOREX_UNIVERSE: dict[str, dict] = {
    "EURUSD": {"name": "Euro / US Dollar", "price": 1.085},
    "GBPUSD": {"name": "British Pound / US Dollar", "price": 1.270},
    "USDJPY": {"name": "US Dollar / Japanese Yen", "price": 155.0},
    "AUDUSD": {"name": "Australian Dollar / US Dollar", "price": 0.665},
    "USDCAD": {"name": "US Dollar / Canadian Dollar", "price": 1.370},
    "USDCHF": {"name": "US Dollar / Swiss Franc", "price": 0.910},
}

COMMODITY_UNIVERSE: dict[str, dict] = {
    "XAUUSD": {"name": "Gold / USD", "price": 2380.0},
    "XAGUSD": {"name": "Silver / USD", "price": 29.0},
    "WTI": {"name": "Crude Oil (WTI)", "price": 78.0},
}

MACRO_UNIVERSE: dict[str, dict] = {
    "DXY": {"name": "US Dollar Index", "price": 105.5},
    "BTC_DOM": {"name": "BTC Dominance", "price": 52.0},
    "US10Y": {"name": "US 10-Year Yield", "price": 4.3},
    "VIX": {"name": "CBOE Volatility Index", "price": 15.0},
}

DEFI_UNIVERSE: dict[str, dict] = {
    "UNI": {"id": "uniswap", "name": "Uniswap", "price": 9.5},
    "AAVE": {"id": "aave", "name": "Aave", "price": 95.0},
    "LDO": {"id": "lido-dao", "name": "Lido DAO", "price": 2.4},
    "CRV": {"id": "curve-dao-token", "name": "Curve DAO", "price": 0.82},
    "MKR": {"id": "maker", "name": "Maker", "price": 2600.0},
    "COMP": {"id": "compound-governance-token", "name": "Compound", "price": 55.0},
    "SUSHI": {"id": "sushi", "name": "Sushi", "price": 1.15},
    "SNX": {"id": "synthetix-network-token", "name": "Synthetix", "price": 3.1},
    "PERP": {"id": "perpetual-protocol", "name": "Perpetual Protocol", "price": 0.95},
    "GMX": {"id": "gmx", "name": "GMX", "price": 42.0},
}


def universe_for(asset_class: AssetClass) -> dict[str, dict]:
    if asset_class == AssetClass.STOCK:
        return STOCK_UNIVERSE
    if asset_class == AssetClass.ETF:
        return ETF_UNIVERSE
    if asset_class == AssetClass.FOREX:
        return FOREX_UNIVERSE
    if asset_class == AssetClass.COMMODITY:
        return COMMODITY_UNIVERSE
    if asset_class == AssetClass.MACRO:
        return MACRO_UNIVERSE
    if asset_class == AssetClass.DEFI:
        return DEFI_UNIVERSE
    return CRYPTO_UNIVERSE


@dataclass
class NormalizedQuote:
    symbol: str
    name: str
    asset_class: AssetClass
    price: float
    provider: str
    source: str
    observed_at: datetime
    change_24h: float | None = None
    change_7d: float | None = None
    change_30d: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None


class QuoteProvider(ABC):
    provider_id: str = "abstract"

    @abstractmethod
    async def quotes(self, symbols: list[str], asset_class: AssetClass) -> list[NormalizedQuote]:
        """Fetch quotes. Never raise; omit symbols that cannot be fetched."""


class CoinGeckoProvider(QuoteProvider):
    provider_id = "coingecko"

    def __init__(self) -> None:
        self._headers = (
            {"x-cg-demo-api-key": settings.COINGECKO_API_KEY}
            if settings.COINGECKO_API_KEY
            else {}
        )

    async def quotes(self, symbols: list[str], asset_class: AssetClass) -> list[NormalizedQuote]:
        if asset_class not in (AssetClass.CRYPTO, AssetClass.DEFI):
            return []
        universe = universe_for(asset_class)
        ids = [universe[s]["id"] for s in symbols if s in universe]
        if not ids:
            return []
        try:
            async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT, headers=self._headers) as client:
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
                    return []
                raw = {c["id"]: c for c in r.json()}
        except Exception:
            return []

        now = datetime.now(UTC)
        out: list[NormalizedQuote] = []
        for sym in symbols:
            meta = universe.get(sym)
            if not meta:
                continue
            coin = raw.get(meta["id"])
            if not coin or not coin.get("current_price"):
                continue
            out.append(NormalizedQuote(
                symbol=sym,
                name=coin.get("name") or meta["name"],
                asset_class=asset_class,
                price=max(float(coin["current_price"]), 0.00000001),
                provider=self.provider_id,
                source="live",
                observed_at=now,
                change_24h=coin.get("price_change_percentage_24h"),
                change_7d=coin.get("price_change_percentage_7d_in_currency"),
                change_30d=coin.get("price_change_percentage_30d_in_currency"),
                volume_24h=coin.get("total_volume"),
                market_cap=coin.get("market_cap"),
                high_24h=coin.get("high_24h"),
                low_24h=coin.get("low_24h"),
            ))
        return out

    async def global_market(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT, headers=self._headers) as client:
                r = await client.get(f"{COINGECKO_URL}/global")
                if r.status_code != 200:
                    return {}
                return r.json().get("data", {})
        except Exception:
            return {}


class TwelveDataProvider(QuoteProvider):
    provider_id = "twelvedata"

    _MACRO_MAP = {
        "DXY": "DXY",
        "US10Y": "US10Y",
        "VIX": "VIX",
        "BTC_DOM": "BTC.D",
    }

    _FOREX_MAP = {
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD",
        "USDCAD": "USD/CAD",
        "USDCHF": "USD/CHF",
    }

    _COMMODITY_MAP = {
        "XAUUSD": "XAU/USD",
        "XAGUSD": "XAG/USD",
        "WTI": "WTI",
    }

    def __init__(self) -> None:
        self._api_key = settings.TWELVE_DATA_API_KEY

    def _provider_symbol(self, symbol: str, asset_class: AssetClass) -> str:
        if asset_class == AssetClass.MACRO:
            return self._MACRO_MAP.get(symbol, symbol)
        if asset_class == AssetClass.FOREX:
            return self._FOREX_MAP.get(symbol, symbol)
        if asset_class == AssetClass.COMMODITY:
            return self._COMMODITY_MAP.get(symbol, symbol)
        return symbol

    async def quotes(self, symbols: list[str], asset_class: AssetClass) -> list[NormalizedQuote]:
        if asset_class == AssetClass.CRYPTO or not self._api_key:
            return []
        universe = universe_for(asset_class)
        out: list[NormalizedQuote] = []
        now = datetime.now(UTC)
        try:
            async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT) as client:
                for sym in symbols:
                    meta = universe.get(sym)
                    if not meta:
                        continue
                    try:
                        r = await client.get(
                            f"{TWELVEDATA_URL}/quote",
                            params={
                                "symbol": self._provider_symbol(sym, asset_class),
                                "apikey": self._api_key,
                            },
                        )
                        j = r.json()
                        if j.get("status") != "ok" or not j.get("close"):
                            continue
                        price = float(j["close"])
                        out.append(NormalizedQuote(
                            symbol=sym,
                            name=meta["name"],
                            asset_class=asset_class,
                            price=max(price, 0.00000001),
                            provider=self.provider_id,
                            source="live",
                            observed_at=now,
                            change_24h=self._to_float(j.get("change")),
                            change_7d=None,
                            change_30d=self._to_float(j.get("thirty_day_movement_pct")),
                            volume_24h=self._to_float(j.get("volume")),
                            market_cap=self._to_float(j.get("market_cap")),
                            high_24h=self._to_float(j.get("high")),
                            low_24h=self._to_float(j.get("low")),
                        ))
                    except Exception:
                        continue
        except Exception:
            pass
        return out

    @staticmethod
    def _to_float(v) -> float | None:
        try:
            if v in (None, "", "-", "--"):
                return None
            return float(v)
        except (TypeError, ValueError):
            return None


class DemoProvider(QuoteProvider):
    provider_id = "demo"

    async def quotes(self, symbols: list[str], asset_class: AssetClass) -> list[NormalizedQuote]:
        universe = universe_for(asset_class)
        now = datetime.now(UTC)
        out: list[NormalizedQuote] = []
        for sym in symbols:
            meta = universe.get(sym) or {"name": sym, "price": 100.0}
            drift = random.uniform(-0.035, 0.035)
            price = max(meta["price"] * (1 + drift), 0.00000001)
            out.append(NormalizedQuote(
                symbol=sym,
                name=meta["name"],
                asset_class=asset_class,
                price=round(price, 6 if price < 1 else 2),
                provider=self.provider_id,
                source="demo",
                observed_at=now,
                change_24h=round(random.uniform(-6, 8), 2),
                change_7d=round(random.uniform(-12, 14), 2),
                change_30d=round(random.uniform(-25, 30), 2),
                volume_24h=random.uniform(5e7, 5e10),
                market_cap=random.uniform(5e8, 2e12),
                high_24h=round(price * 1.02, 2),
                low_24h=round(price * 0.98, 2),
            ))
        return out


class ProviderRegistry:
    def __init__(self) -> None:
        self._crypto = CoinGeckoProvider()
        self._securities = TwelveDataProvider() if settings.TWELVE_DATA_API_KEY else None
        self._demo = DemoProvider()
        self._force_demo = False

    def force_demo(self, enabled: bool = True) -> None:
        """Explicit, observable opt-in to demo quotes regardless of mode.
        Never automatic — must be called deliberately (e.g. a CLI override).
        Demo quotes keep source="demo" so they can never look live."""
        self._force_demo = enabled

    def providers_for(self, asset_class: AssetClass) -> list[QuoteProvider]:
        if self._force_demo or settings.MARKET_DATA_MODE == "demo":
            return [self._demo]

        # live mode: real providers only, missing data stays missing.
        if asset_class in (AssetClass.CRYPTO, AssetClass.DEFI):
            return [self._crypto]
        if asset_class in (
            AssetClass.STOCK,
            AssetClass.ETF,
            AssetClass.MACRO,
            AssetClass.FOREX,
            AssetClass.COMMODITY,
        ):
            return [self._securities] if self._securities else []
        return []

    async def crypto_global(self) -> dict:
        if self._force_demo or settings.MARKET_DATA_MODE == "demo":
            return {}
        return await self._crypto.global_market()

    async def get_quotes(
        self, symbols: list[str], asset_class: AssetClass
    ) -> dict[str, NormalizedQuote]:
        """Fetch quotes from the mode-locked provider chain. No cross-provider
        fallback: a symbol that fails stays absent so the caller can decide
        how honestly to report the gap."""
        seen: dict[str, NormalizedQuote] = {}
        for provider in self.providers_for(asset_class):
            for q in await provider.quotes(symbols, asset_class):
                seen.setdefault(q.symbol, q)
        return seen


market_providers = ProviderRegistry()


# Per-symbol factor betas for the demo price series. Positive beta rides the
# shared market factor (risk-on), negative beta rides it inversely (risk-off /
# defensive). Coherent betas give the demo correlation radar plausible signs.
_DEMO_FACTOR_BETAS: dict[str, float] = {
    # risk assets (high beta)
    "BTC": 1.1, "ETH": 1.0, "SOL": 0.9,
    "COIN": 1.2, "MSTR": 1.3, "NVDA": 1.0, "TSLA": 1.0, "AMD": 1.1,
    "PLTR": 1.1, "SQ": 1.0, "HOOD": 1.1, "META": 1.0, "AMZN": 0.9,
    "AAPL": 0.8, "MSFT": 0.8, "GOOGL": 0.9, "NFLX": 0.8,
    "QQQ": 0.9, "SPY": 0.7, "IWM": 0.7, "ARKK": 1.1, "VTI": 0.7,
    "EEM": 0.6, "AUDUSD": 0.7, "WTI": 0.6,
    # DeFi tokens track the crypto risk factor closely
    "UNI": 1.2, "AAVE": 1.1, "LDO": 1.2, "CRV": 1.1, "MKR": 0.9,
    "COMP": 1.1, "SUSHI": 1.2, "SNX": 1.1, "PERP": 0.9, "GMX": 1.0,
    # moderately positive
    "EURUSD": 0.5, "GBPUSD": 0.4, "XAUUSD": 0.35, "XAGUSD": 0.6,
    # defensive / safe havens (inverse beta)
    "TLT": -0.6, "DXY": -0.7, "VIX": -0.8, "USDJPY": -0.3,
    "USDCAD": -0.3, "USDCHF": -0.4, "US10Y": 0.2, "BTC_DOM": 0.2,
}

# Cached deterministic market factor (shared across all symbols). A mild
# positive drift keeps the demo scenario coherent (risk-on bias): risk assets
# tend upward while inverse-beta names (TLT/DXY/VIX) drift down, so the regime
# engine sees a plausible, stable cross-asset picture rather than noise.
_DEMO_MARKET_FACTOR: dict[int, list[float]] = {}


def _demo_market_factor(points: int) -> list[float]:
    cached = _DEMO_MARKET_FACTOR.get(points)
    if cached is None:
        rng = random.Random(int(hashlib.sha256(b"hf-demo-market-factor").hexdigest()[:8], 16))
        cached = [rng.gauss(0.0009, 0.007) for _ in range(points)]
        _DEMO_MARKET_FACTOR[points] = cached
    return cached


def demo_price_series(symbol: str, asset_class: AssetClass, points: int = 90) -> list[float]:
    """Deterministic synthetic price series with plausible cross-asset structure.

    Every symbol loads a shared market factor (fixed, seeded per window
    length) plus per-symbol idiosyncratic noise. Betas assign sign/direction
    so inverse relationships (TLT/bonds, DXY, VIX) come out negative against
    risk assets. Seeded by symbol+class so a given series is stable across
    calls. Demo/simulated — never presented as live measurement.
    """
    meta = universe_for(asset_class).get(symbol) or {"price": 100.0}
    base = meta["price"]
    beta = _DEMO_FACTOR_BETAS.get(symbol, 0.5)
    seed = int(hashlib.sha256(f"{asset_class.value}:{symbol}:series".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    factor = _demo_market_factor(points)
    series: list[float] = []
    price = base
    for i in range(points):
        price = max(price * (1.0 + beta * factor[i] + rng.gauss(0.0, 0.005)), 0.00000001)
        series.append(round(price, 6 if price < 1 else 2))
    return series
