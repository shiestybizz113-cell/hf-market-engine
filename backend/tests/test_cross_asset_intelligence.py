"""
Tests for the Phase 1B cross-asset intelligence engine.

Covers the demo-series generator, correlation math (pearson/log_returns),
the CorrelationEngine pair scan, the RegimeEngine factor/classification
logic, the AlphaScanner momentum ranking, the cross-asset idea generator in
signal_engine, and the new API surface (/regime, /alpha, /ideas/cross-asset).

All market data runs in demo mode (forced by conftest): the engines must
stamp source=demo / is_simulated=True so nothing reads as live measurement.
"""

import pytest

from app.core.market_providers import demo_price_series
from app.engines.alpha_scanner import AlphaScanner
from app.engines.correlation_engine import CorrelationEngine, log_returns, pearson, _status_for
from app.engines.regime_engine import RegimeEngine, _Signal, total_returns
from app.engines.signal_engine import signal_engine
from app.models.schemas import AssetClass, SignalDirection, SignalType

# --------------------------------------------------------------------------
# Demo series + math helpers
# --------------------------------------------------------------------------

def test_demo_price_series_is_deterministic():
    a = demo_price_series("BTC", AssetClass.CRYPTO, 90)
    b = demo_price_series("BTC", AssetClass.CRYPTO, 90)
    assert a == b
    assert len(a) == 90
    assert all(p > 0 for p in a)


def test_demo_price_series_differs_per_symbol():
    a = demo_price_series("BTC", AssetClass.CRYPTO, 60)
    b = demo_price_series("ETH", AssetClass.CRYPTO, 60)
    assert a != b


def test_demo_price_series_cross_class_uses_same_seed_domain():
    # Symbol identity includes class: BTC-as-crypto vs BTC-as-xxx must anchor
    # to the per-class universe price but stay deterministic per call.
    a = demo_price_series("XAUUSD", AssetClass.COMMODITY, 30)
    b = demo_price_series("XAUUSD", AssetClass.COMMODITY, 30)
    assert a == b
    assert a[0] > 0


@pytest.mark.parametrize("cls", [
    AssetClass.CRYPTO, AssetClass.DEFI, AssetClass.STOCK, AssetClass.ETF,
    AssetClass.FOREX, AssetClass.COMMODITY, AssetClass.MACRO,
])
def test_demo_price_series_all_classes(cls):
    series = demo_price_series("ZZZ", cls, 20)
    assert len(series) == 20
    assert all(p > 0 for p in series)


def test_pearson_perfect_positive():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert pearson(x, y) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert pearson(x, y) == pytest.approx(-1.0)


def test_pearson_constant_series_returns_none():
    # Constant series has zero variance — returns None rather than dividing by 0.
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 5.0, 5.0, 5.0, 5.0]
    assert pearson(x, y) is None


def test_pearson_short_series_returns_none():
    assert pearson([1.0, 2.0], [1.0, 2.0]) is None
    assert pearson([1.0], [1.0]) is None
    assert pearson([], []) is None


def test_pearson_mismatched_lengths_none():
    assert pearson([1.0, 2.0, 3.0], [1.0, 2.0]) is None


def test_log_returns_length_and_sign():
    series = [1.0, 1.1, 0.99, 1.05]
    returns = log_returns(series)
    assert len(returns) == len(series) - 1
    assert returns[0] == pytest.approx(0.09531, rel=1e-3)
    assert returns[1] < 0
    assert returns[2] > 0


def test_log_returns_guards_non_positive():
    assert log_returns([0.0, 1.0, 2.0]) == [log_returns([1.0, 2.0])[0]]
    assert log_returns([-1.0, 1.0]) == []


def test_total_returns():
    assert total_returns([100.0, 105.0, 110.0]) == pytest.approx(0.10)
    assert total_returns([100.0]) is None
    assert total_returns([]) is None


# --------------------------------------------------------------------------
# CorrelationEngine
# --------------------------------------------------------------------------

async def test_correlation_scan_returns_labelled_pairs():
    engine = CorrelationEngine()
    pairs = await engine.scan(points=60)
    assert pairs, "expected at least one computable correlation pair"
    for p in pairs:
        assert p.asset_a and p.asset_b
        assert -1.0 <= p.correlation <= 1.0
        assert p.pair and p.relationship_type
        assert p.status
        assert p.source == "demo"
        assert p.is_simulated is True


async def test_correlation_scan_deterministic():
    engine = CorrelationEngine()
    one = await engine.scan(points=60)
    two = await engine.scan(points=60)
    assert [(p.pair, p.correlation) for p in one] == [
        (p.pair, p.correlation) for p in two
    ]


async def test_correlation_scan_uses_min_length_or_skips():
    engine = CorrelationEngine()
    # Tiny windows cannot produce a correlation — engine must skip cleanly.
    pairs = await engine.scan(points=2)
    assert pairs == []


def test_correlation_status_buckets():
    # _status_for(corr) — magnitude drives the bucket, sign drives the label
    # for the mid-strength band.
    assert _status_for(0.0)[0] == "Decoupled"
    assert _status_for(0.8)[0] == "Locked"
    assert _status_for(-0.8)[0] == "Locked"
    assert _status_for(0.4)[0] == "Moving in tandem"
    assert _status_for(-0.4)[0] == "Diverging"
    assert _status_for(0.05)[0] == "Decoupled"


# --------------------------------------------------------------------------
# RegimeEngine
# --------------------------------------------------------------------------

def test_regime_signals_build_from_series():
    engine = RegimeEngine()
    series_map = {
        "SPY": [100.0, 110.0, 120.0],
        "TLT": [100.0, 95.0, 90.0],
        "DXY": [100.0, 99.0, 98.0],
        "BTC": [100.0, 120.0, 140.0],
        "VIX": [15.0, 22.0, 25.0],
        "XAUUSD": [100.0, 108.0, 116.0],
    }
    signals = engine._build_signals(series_map)
    assert len(signals) == 6
    spy = next(s for s in signals if s.name.startswith("Equities"))
    assert spy.direction > 0
    vix = next(s for s in signals if s.name.startswith("Volatility"))
    assert vix.direction < 0  # VIX above 20 is a risk-off tell


def test_regime_classify_risk_on():
    engine = RegimeEngine()
    signals = [
        _Signal("Equities (SPY)", "up", 1),
        _Signal("Long bonds (TLT)", "down", 1),
        _Signal("Volatility (VIX)", "low", 1),
    ]
    score, key = engine._classify(signals)
    assert key == "risk_on"
    assert 0 <= score <= 100


def test_regime_classify_risk_off():
    engine = RegimeEngine()
    signals = [
        _Signal("Equities (SPY)", "down", -1),
        _Signal("Long bonds (TLT)", "up", -1),
        _Signal("Volatility (VIX)", "high", -1),
    ]
    score, key = engine._classify(signals)
    assert key == "risk_off"
    assert 0 <= score <= 100


def test_regime_classify_crypto_bull():
    engine = RegimeEngine()
    signals = [
        _Signal("Equities (SPY)", "flat", -1),
        _Signal("Crypto (BTC)", "strong", 1),
        _Signal("Dollar (DXY)", "up", 1),
    ]
    score, key = engine._classify(signals)
    assert key == "crypto_bull"
    assert 0 <= score <= 100


def test_regime_classify_empty_is_mixed():
    engine = RegimeEngine()
    score, key = engine._classify([])
    assert key == "mixed"
    assert 0 <= score <= 100


async def test_regime_snapshot_shape():
    engine = RegimeEngine()
    snap = await engine.snapshot(points=60)
    assert snap.regime in {
        "risk_on", "risk_off", "crypto_bull",
        "dollar_strength", "gold_bid", "mixed",
    }
    assert 0 <= snap.score <= 100
    assert snap.source == "demo"
    assert snap.is_simulated is True
    assert snap.last_updated is not None
    assert snap.factors


# --------------------------------------------------------------------------
# AlphaScanner
# --------------------------------------------------------------------------

async def test_alpha_scan_returns_ranked_results():
    scanner = AlphaScanner()
    result = await scanner.scan(limit=20)
    assert result.is_simulated is True
    assert result.anomaly_detection == "disabled (demo)"
    assert len(result.items) <= 20
    assert "Research only" in result.disclaimer
    assert result.generated_at is not None

    scores = [it.momentum_score for it in result.items]
    assert all(0 <= s <= 100 for s in scores)
    assert scores == sorted(scores, reverse=True)


async def test_alpha_scan_covers_asset_classes():
    scanner = AlphaScanner()
    result = await scanner.scan(limit=100)
    classes = {it.asset_class for it in result.items}
    assert AssetClass.CRYPTO in classes
    assert AssetClass.DEFI in classes
    assert AssetClass.STOCK in classes
    assert AssetClass.ETF in classes
    assert AssetClass.FOREX in classes
    assert AssetClass.COMMODITY in classes


async def test_alpha_scan_limit_bound():
    scanner = AlphaScanner()
    small = await scanner.scan(limit=5)
    assert len(small.items) == 5


def test_momentum_drivers_recorded():
    from app.models.schemas import PriceQuote

    quote = PriceQuote(
        symbol="TEST", asset_class=AssetClass.STOCK, name="Test",
        price=100.0, change_24h=1.5,
        change_7d=-2.0, change_30d=0.5, source="demo",
    )
    scanner = AlphaScanner()
    score, drivers = scanner._momentum(quote)
    assert 0 <= score <= 100
    assert len(drivers) == 3
    assert any("24h +1.5%" in d for d in drivers)


# --------------------------------------------------------------------------
# Cross-asset ideas
# --------------------------------------------------------------------------

async def test_cross_asset_ideas_are_well_formed():
    ideas = await signal_engine.generate_cross_asset_ideas(limit=5)
    assert len(ideas) <= 5
    for idea in ideas:
        assert idea.asset
        assert idea.asset_class in {
            AssetClass.ETF, AssetClass.CRYPTO, AssetClass.COMMODITY,
        }
        assert idea.direction in {SignalDirection.BULLISH, SignalDirection.BEARISH, SignalDirection.NEUTRAL}
        assert idea.signal_type in set(SignalType)
        assert idea.thesis
        assert 0 <= idea.confidence <= 100
        assert 0 <= idea.risk_score <= 100


# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------

async def test_regime_endpoint(client):
    r = await client.get("/api/market/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "demo"
    assert body["is_simulated"] is True
    assert 0 <= body["score"] <= 100


async def test_alpha_endpoint(client):
    r = await client.get("/api/market/alpha")
    assert r.status_code == 200
    body = r.json()
    assert body["anomaly_detection"] == "disabled (demo)"
    assert len(body["items"]) <= 20


async def test_alpha_endpoint_limit_validation(client):
    r = await client.get("/api/market/alpha?limit=2")
    assert r.status_code == 422


async def test_correlations_endpoint(client):
    r = await client.get("/api/market/correlations")
    assert r.status_code == 200
    body = r.json()
    assert body, "correlation radar must not be empty in demo mode"
    assert all(p["source"] == "demo" and p["is_simulated"] is True for p in body)


async def test_cross_asset_ideas_endpoint(client):
    r = await client.get("/api/market/ideas/cross-asset")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    if body:
        assert body[0]["thesis"]


async def test_universe_still_returns_all_classes(client):
    r = await client.get("/api/market/universe")
    assert r.status_code == 200
    keys = set(r.json().keys())
    assert keys == {
        "crypto", "stocks", "etfs", "forex", "commodities", "macro", "defi",
    }
