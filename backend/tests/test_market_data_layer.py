"""
Tests for the Phase 1A data layer: multi-asset universes and providers.

Covers the AssetClass enum (incl. commodity), universe completeness against
the product's symbol spec, universe_for routing, the DemoProvider contract
(every universe symbol yields a provenance-stamped quote), and the wiring of
forex/commodity through the TwelveData mapping table.
"""

import pytest

from app.core.market_providers import (
    COMMODITY_UNIVERSE,
    CRYPTO_UNIVERSE,
    ETF_UNIVERSE,
    FOREX_UNIVERSE,
    MACRO_UNIVERSE,
    STOCK_UNIVERSE,
    DemoProvider,
    ProviderRegistry,
    universe_for,
)
from app.models.schemas import AssetClass

# Product-spec symbol lists (mirrors the multi-asset expansion spec).
EXPECTED_CRYPTO = {"BTC", "ETH", "SOL", "LINK", "AVAX", "DOGE", "XRP", "ADA", "DOT", "MATIC"}
EXPECTED_STOCKS = {
    "COIN", "MSTR", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN",
    "GOOGL", "META", "NFLX", "AMD", "PLTR", "SQ", "HOOD",
}
EXPECTED_ETFS = {"SPY", "QQQ", "IWM", "GLD", "TLT", "ARKK", "VTI", "EEM"}
EXPECTED_FOREX = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"}
EXPECTED_COMMODITIES = {"XAUUSD", "XAGUSD", "WTI"}
EXPECTED_MACRO = {"DXY", "BTC_DOM", "US10Y", "VIX"}


# --------------------------------------------------------------------------
# AssetClass enum
# --------------------------------------------------------------------------

def test_commodity_asset_class_exists():
    assert AssetClass.COMMODITY.value == "commodity"
    # The enum covers every asset class the universes expect (no orphan values).
    assert {u.value for u in AssetClass} >= {
        "crypto", "stock", "etf", "forex", "commodity", "macro", "defi",
    }


# --------------------------------------------------------------------------
# Universe completeness
# --------------------------------------------------------------------------

@pytest.mark.parametrize("universe,expected", [
    (CRYPTO_UNIVERSE, EXPECTED_CRYPTO),
    (STOCK_UNIVERSE, EXPECTED_STOCKS),
    (ETF_UNIVERSE, EXPECTED_ETFS),
    (FOREX_UNIVERSE, EXPECTED_FOREX),
    (COMMODITY_UNIVERSE, EXPECTED_COMMODITIES),
    (MACRO_UNIVERSE, EXPECTED_MACRO),
])
def test_universe_contains_spec_symbols(universe, expected):
    assert expected <= set(universe), f"Missing symbols: {expected - set(universe)}"


def test_universe_entries_have_names_and_prices():
    for universe in (
        CRYPTO_UNIVERSE, STOCK_UNIVERSE, ETF_UNIVERSE,
        FOREX_UNIVERSE, COMMODITY_UNIVERSE, MACRO_UNIVERSE,
    ):
        for sym, meta in universe.items():
            assert meta["name"], f"{sym} is missing a display name"
            assert meta["price"] > 0, f"{sym} has a non-positive base price"


def test_forex_prices_are_realistic_pair_scales():
    """FX majors are quoted in the 0.6–160 range; spot a unit-error early."""
    for sym, meta in FOREX_UNIVERSE.items():
        assert 0.5 < meta["price"] < 200, f"{sym} base price {meta['price']} is off-scale"


def test_crypto_entries_have_coingecko_ids():
    for sym, meta in CRYPTO_UNIVERSE.items():
        assert meta["id"], f"{sym} is missing its CoinGecko id"


@pytest.mark.parametrize("asset_class,universe", [
    (AssetClass.CRYPTO, CRYPTO_UNIVERSE),
    (AssetClass.STOCK, STOCK_UNIVERSE),
    (AssetClass.ETF, ETF_UNIVERSE),
    (AssetClass.FOREX, FOREX_UNIVERSE),
    (AssetClass.COMMODITY, COMMODITY_UNIVERSE),
    (AssetClass.MACRO, MACRO_UNIVERSE),
])
def test_universe_for_routes_all_supported_classes(asset_class, universe):
    assert universe_for(asset_class) is universe


def test_universe_for_defaults_unlisted_class_to_crypto():
    assert universe_for(AssetClass.DEFI) is CRYPTO_UNIVERSE


# --------------------------------------------------------------------------
# DemoProvider contract
# --------------------------------------------------------------------------

@pytest.mark.parametrize("asset_class", [
    AssetClass.CRYPTO,
    AssetClass.STOCK,
    AssetClass.ETF,
    AssetClass.FOREX,
    AssetClass.COMMODITY,
    AssetClass.MACRO,
])
async def test_demo_provider_quotes_every_universe_symbol(asset_class):
    provider = DemoProvider()
    symbols = list(universe_for(asset_class).keys())
    quotes = await provider.quotes(symbols, asset_class)
    got = {q.symbol for q in quotes}
    assert got == set(symbols), f"{asset_class}: missing {set(symbols) - got}"


def test_demo_quotes_are_provenance_stamped():
    provider = DemoProvider()

    async def _one():
        return await provider.quotes(["EURUSD", "GBPUSD", "USDJPY"], AssetClass.FOREX)

    import asyncio

    quotes = asyncio.run(_one())
    assert quotes
    for q in quotes:
        assert q.provider == "demo"
        assert q.source == "demo"
        assert q.observed_at is not None


def test_demo_quotes_never_zero_or_negative():
    provider = DemoProvider()

    async def _all():
        out = []
        for asset_class in (
            AssetClass.CRYPTO, AssetClass.STOCK, AssetClass.ETF,
            AssetClass.FOREX, AssetClass.COMMODITY, AssetClass.MACRO,
        ):
            out.extend(await provider.quotes(list(universe_for(asset_class)), asset_class))
        return out

    import asyncio

    for q in asyncio.run(_all()):
        assert q.price > 0


# --------------------------------------------------------------------------
# TwelveData mapping wiring (forex / commodity / macro)
# --------------------------------------------------------------------------

def test_twelvedata_provider_symbol_map():
    from app.core.market_providers import TwelveDataProvider
    provider = TwelveDataProvider.__new__(TwelveDataProvider)
    assert provider._provider_symbol("EURUSD", AssetClass.FOREX) == "EUR/USD"
    assert provider._provider_symbol("USDJPY", AssetClass.FOREX) == "USD/JPY"
    assert provider._provider_symbol("XAUUSD", AssetClass.COMMODITY) == "XAU/USD"
    assert provider._provider_symbol("WTI", AssetClass.COMMODITY) == "WTI"
    assert provider._provider_symbol("US10Y", AssetClass.MACRO) == "US10Y"
    assert provider._provider_symbol("BTC_DOM", AssetClass.MACRO) == "BTC.D"
    # Plain security symbols pass through untouched.
    assert provider._provider_symbol("NVDA", AssetClass.STOCK) == "NVDA"


# --------------------------------------------------------------------------
# ProviderRegistry routing
# --------------------------------------------------------------------------

def test_registry_routes_forex_and_commodity_to_securities_provider(monkeypatch):
    import app.core.market_providers as mp

    monkeypatch.setattr(mp.settings, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(mp.settings, "MARKET_DATA_MODE", "live")

    registry = ProviderRegistry()
    for asset_class in (AssetClass.FOREX, AssetClass.COMMODITY):
        providers = registry.providers_for(asset_class)
        assert providers, f"{asset_class} should have a provider when keyed"
        assert all(p.provider_id == "twelvedata" for p in providers)


def test_registry_demo_mode_forces_demo_for_all_classes(monkeypatch):
    import app.core.market_providers as mp

    monkeypatch.setattr(mp.settings, "MARKET_DATA_MODE", "demo")

    registry = ProviderRegistry()
    for asset_class in (
        AssetClass.CRYPTO, AssetClass.STOCK, AssetClass.ETF,
        AssetClass.FOREX, AssetClass.COMMODITY, AssetClass.MACRO,
    ):
        providers = registry.providers_for(asset_class)
        assert providers
        assert all(p.provider_id == "demo" for p in providers)


async def test_registry_get_quotes_covers_commodity_in_demo_mode(monkeypatch):
    import app.core.market_providers as mp

    monkeypatch.setattr(mp.settings, "MARKET_DATA_MODE", "demo")
    registry = ProviderRegistry()
    quotes = await registry.get_quotes(["XAUUSD", "WTI"], AssetClass.COMMODITY)
    assert set(quotes) == {"XAUUSD", "WTI"}


# --------------------------------------------------------------------------
# API surface (needs the mongo-backed client fixture)
# --------------------------------------------------------------------------

async def test_universe_endpoint_includes_forex_and_commodity(client):
    r = await client.get("/api/market/universe")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"crypto", "stocks", "etfs", "forex", "commodities"}
    assert "XAUUSD" in body["commodities"]
    assert "EURUSD" in body["forex"]


async def test_movers_endpoint_works_for_each_asset_class(client):
    for asset_class in ("crypto", "stock", "etf", "forex", "commodity", "macro"):
        r = await client.get(f"/api/market/movers?asset_class={asset_class}")
        assert r.status_code == 200, f"{asset_class} movers failed: {r.text}"
        body = r.json()
        assert "gainers" in body and "losers" in body
        for item in body["gainers"] + body["losers"]:
            assert item["source"] == "demo"
            assert item["price"] > 0


async def test_prices_endpoint_forex(client):
    r = await client.get("/api/market/prices?asset_class=forex&symbols=EURUSD,USDJPY")
    assert r.status_code == 200
    quotes = r.json()
    assert {q["symbol"] for q in quotes} == {"EURUSD", "USDJPY"}
    assert all(q["asset_class"] == "forex" for q in quotes)


async def test_prices_endpoint_commodity(client):
    r = await client.get("/api/market/prices?asset_class=commodity&symbols=XAUUSD,WTI")
    assert r.status_code == 200
    quotes = r.json()
    assert {q["symbol"] for q in quotes} == {"XAUUSD", "WTI"}
    assert all(q["asset_class"] == "commodity" for q in quotes)
