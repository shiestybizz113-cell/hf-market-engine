"""
DB-free tests for the Paper Execution Engine.

Covers the pure logic that does not touch MongoDB: the algo catalog, slice
count/size math, child-order simulation, algo recommendation, and parent
model round-tripping. The DB-touching submit/get/analytics paths are covered
by the API integration tests in test_core.py.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.core import config as config_mod
from app.engines import execution_engine as ee
from app.engines.execution_engine import ALGO_CATALOG, PaperExecutionEngine
from app.models.execution import (
    ChildOrder,
    ExecutionAlgoConfig,
    ExecutionAlgoType,
    ExecutionStatus,
    ExecutionUrgency,
    ParentOrder,
    ParentOrderCreate,
    VenueType,
)
from app.models.schemas import AssetClass

ENGINE = PaperExecutionEngine()
EQ = AssetClass.STOCK


# --------------------------------------------------------------------------
# Algo catalog
# --------------------------------------------------------------------------

def test_catalog_has_one_entry_per_algo_type():
    types = {entry.algo_type for entry in ALGO_CATALOG}
    assert types == set(ExecutionAlgoType)


def test_catalog_entries_are_educational_and_phase2_ready():
    for entry in ALGO_CATALOG:
        assert entry.name
        assert entry.short_description
        assert entry.how_it_works
        assert entry.best_for
        assert entry.weaknesses
        assert entry.crypto_notes
        assert entry.typical_params
        assert entry.phase2_ready


# --------------------------------------------------------------------------
# Slice count / size
# --------------------------------------------------------------------------

def _cfg(**overrides) -> ExecutionAlgoConfig:
    params = dict(
        algo_type=ExecutionAlgoType.TWAP,
        duration_minutes=30,
        slice_interval_seconds=30,
    )
    params.update(overrides)
    return ExecutionAlgoConfig(**params)


def test_market_orders_are_a_single_slice():
    assert ENGINE._slice_count(ExecutionAlgoType.MARKET, 100.0, _cfg()) == 1


def test_duration_driven_slice_count_is_bounded():
    n = ENGINE._slice_count(ExecutionAlgoType.TWAP, 100.0, _cfg(duration_minutes=30))
    assert 2 <= n <= 60
    # 30 min * 60s / 30s interval = 60 expected
    assert n == 60


def test_duration_at_least_two_slices_even_for_tiny_windows():
    n = ENGINE._slice_count(ExecutionAlgoType.TWAP, 100.0, _cfg(duration_minutes=1))
    assert n == 2


def test_volume_driven_slice_count_for_large_orders():
    n = ENGINE._slice_count(ExecutionAlgoType.TWAP, 500.0, _cfg(duration_minutes=None))
    assert 12 <= n <= 24


def test_volume_driven_slice_count_for_small_orders():
    n = ENGINE._slice_count(ExecutionAlgoType.TWAP, 10.0, _cfg(duration_minutes=None))
    assert 4 <= n <= 10


def test_slice_size_is_uniform_for_twap():
    sizes = [ENGINE._slice_size(ExecutionAlgoType.TWAP, 100.0, 4, i) for i in range(4)]
    assert sizes == [25.0, 25.0, 25.0, 25.0]


def test_slice_size_variable_for_weighted_algos():
    for algo in (ExecutionAlgoType.VWAP, ExecutionAlgoType.POV, ExecutionAlgoType.ADAPTIVE):
        sizes = {ENGINE._slice_size(algo, 100.0, 4, i) for i in range(4)}
        assert len(sizes) > 1, f"{algo} should randomize slice weights"


# --------------------------------------------------------------------------
# Algo recommender
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommend_market_for_critical_urgency_or_tiny_size():
    cfg = await ENGINE.recommend_algo("BTC", AssetClass.CRYPTO, "buy", 5.0, ExecutionUrgency.CRITICAL)
    assert cfg.algo_type == ExecutionAlgoType.MARKET
    tiny = await ENGINE.recommend_algo("BTC", AssetClass.CRYPTO, "buy", 1.0, ExecutionUrgency.MEDIUM)
    assert tiny.algo_type == ExecutionAlgoType.MARKET


@pytest.mark.asyncio
async def test_recommend_shortfall_for_high_urgency():
    cfg = await ENGINE.recommend_algo("AAPL", EQ, "buy", 100.0, ExecutionUrgency.HIGH)
    assert cfg.algo_type == ExecutionAlgoType.IMPLEMENTATION_SHORTFALL
    assert cfg.duration_minutes == 30
    assert cfg.alpha_signal == 0.3


@pytest.mark.asyncio
async def test_recommend_twap_for_low_urgency():
    cfg = await ENGINE.recommend_algo("AAPL", EQ, "sell", 100.0, ExecutionUrgency.LOW)
    assert cfg.algo_type == ExecutionAlgoType.TWAP
    assert cfg.duration_minutes == 90


@pytest.mark.asyncio
async def test_recommend_adaptive_for_medium_urgency():
    cfg = await ENGINE.recommend_algo("AAPL", EQ, "buy", 100.0, ExecutionUrgency.MEDIUM)
    assert cfg.algo_type == ExecutionAlgoType.ADAPTIVE
    assert cfg.duration_minutes == 60


# --------------------------------------------------------------------------
# Child order simulation
# --------------------------------------------------------------------------

def _order(side: str = "buy", qty: float = 100.0, limit_price=None) -> ParentOrderCreate:
    return ParentOrderCreate(
        asset="AAPL",
        asset_class=EQ,
        side=side,
        quantity=qty,
        limit_price=limit_price,
        algo=ExecutionAlgoConfig(
            algo_type=ExecutionAlgoType.MARKET,
            urgency=ExecutionUrgency.MEDIUM,
        ),
        paper_mode=True,
    )


def _empty_ctx():
    return {"adv": None, "sigma_daily": None}


@pytest.mark.asyncio
async def test_simulate_market_children_fill_full_quantity():
    order = _order(side="buy", qty=100.0)
    start = datetime.now(UTC)
    children = await ENGINE._simulate_children(
        order, arrival=100.0, parent_id="p1", now=start, impact_ctx=_empty_ctx()
    )
    assert len(children) == 1
    assert children[0].filled_qty == 100.0
    assert children[0].status == ExecutionStatus.FILLED
    assert children[0].venue_type in (VenueType.EXCHANGE, VenueType.DEX, VenueType.DARK)
    assert children[0].fees >= 0


@pytest.mark.asyncio
async def test_simulate_market_buy_without_market_data_fills_at_arrival():
    """No ADV/sigma → impact is 0 → fill exactly at arrival (no invented costs)."""
    order = _order(side="buy", qty=100.0)
    children = await ENGINE._simulate_children(
        order, arrival=100.0, parent_id="p1",
        now=datetime.now(UTC), impact_ctx=_empty_ctx(),
    )
    assert children[0].avg_price == 100.0


@pytest.mark.asyncio
async def test_simulate_respects_buy_limit_price(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "IMPACT_MODEL", "legacy_random", raising=False)
    monkeypatch.setattr(ee.settings, "IMPACT_MODEL", "legacy_random", raising=False)
    order = _order(side="buy", qty=100.0, limit_price=99.0)
    children = await ENGINE._simulate_children(
        order, arrival=100.0, parent_id="p1",
        now=datetime.now(UTC), impact_ctx=_empty_ctx(),
    )
    assert children[0].avg_price <= 99.0


@pytest.mark.asyncio
async def test_simulate_respects_sell_limit_price(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "IMPACT_MODEL", "legacy_random", raising=False)
    monkeypatch.setattr(ee.settings, "IMPACT_MODEL", "legacy_random", raising=False)
    order = _order(side="sell", qty=100.0, limit_price=101.0)
    children = await ENGINE._simulate_children(
        order, arrival=100.0, parent_id="p1",
        now=datetime.now(UTC), impact_ctx=_empty_ctx(),
    )
    assert children[0].avg_price >= 101.0


@pytest.mark.asyncio
async def test_simulate_buy_and_sell_move_opposite_directions(monkeypatch):
    ctx = {"adv": 30_000_000_000.0, "sigma_daily": 0.03}

    monkeypatch.setattr(config_mod.settings, "IMPACT_MODEL", "sqrt_law_v1", raising=False)
    monkeypatch.setattr(ee.settings, "IMPACT_MODEL", "sqrt_law_v1", raising=False)

    start = datetime.now(UTC)
    buy = await ENGINE._simulate_children(
        _order(side="buy", qty=100.0), arrival=100.0, parent_id="p1", now=start, impact_ctx=ctx
    )
    sell = await ENGINE._simulate_children(
        _order(side="sell", qty=100.0), arrival=100.0, parent_id="p1", now=start, impact_ctx=ctx
    )
    # Buys fill above arrival, sells below — impact is directional.
    assert buy[0].avg_price > 100.0
    assert sell[0].avg_price < 100.0


@pytest.mark.asyncio
async def test_simulate_twap_splits_into_children(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "IMPACT_MODEL", "none", raising=False)
    monkeypatch.setattr(ee.settings, "IMPACT_MODEL", "none", raising=False)
    order = _order(side="buy", qty=100.0)
    order.algo = ExecutionAlgoConfig(
        algo_type=ExecutionAlgoType.TWAP,
        duration_minutes=30,
        slice_interval_seconds=30,
    )
    children = await ENGINE._simulate_children(
        order, arrival=100.0, parent_id="p1",
        now=datetime.now(UTC), impact_ctx=_empty_ctx(),
    )
    assert len(children) > 1
    total = sum(c.filled_qty for c in children)
    assert total == pytest.approx(100.0, abs=1e-3)
    assert all(c.parent_id == "p1" for c in children)


# --------------------------------------------------------------------------
# Model round-trip
# --------------------------------------------------------------------------

def test_to_model_round_trips_parent_document():
    child = ChildOrder(
        id=str(uuid.uuid4()),
        parent_id="p1",
        venue="exchange-primary",
        venue_type=VenueType.EXCHANGE,
        side="buy",
        quantity=100.0,
        filled_qty=100.0,
        avg_price=100.0,
        status=ExecutionStatus.FILLED,
    )
    doc = {
        "_id": "p1",
        "user_id": "u1",
        "asset": "AAPL",
        "asset_class": EQ.value,
        "side": "buy",
        "quantity": 100.0,
        "filled_qty": 100.0,
        "remaining_qty": 0.0,
        "avg_fill_price": 100.0,
        "arrival_price": 100.0,
        "limit_price": None,
        "status": "filled",
        "algo": {"algo_type": "twap", "urgency": "medium", "duration_minutes": 30},
        "paper_mode": True,
        "strategy_id": None,
        "child_orders": [child.model_dump(mode="json")],
        "created_at": datetime.now(UTC),
        "started_at": None,
        "completed_at": datetime.now(UTC),
        "implementation_shortfall_bps": 5.0,
        "vwap_deviation_bps": None,
        "notes": "test",
        "risk_score_at_submission": None,
        "rejection_reason": None,
    }
    parsed = ENGINE._to_model(doc)
    assert isinstance(parsed, ParentOrder)
    assert parsed.id == "p1"
    assert parsed.asset_class == EQ
    assert parsed.status == ExecutionStatus.FILLED
    assert parsed.avg_fill_price == 100.0
    assert len(parsed.child_orders) == 1


@pytest.mark.asyncio
async def test_submit_refuses_live_trading():
    """Phase 1 paper-only: live mode must be refused before anything else."""
    non_paper = _order(side="buy", qty=100.0)
    non_paper.paper_mode = False
    with pytest.raises(ValueError, match="paper_mode"):
        await ENGINE.submit_parent_order("u1", non_paper)


# --------------------------------------------------------------------------
# DB-touching integration paths (needs the test Mongo fixture)
# --------------------------------------------------------------------------


async def _demo_order():
    return ParentOrderCreate(
        asset="BTC",
        asset_class=AssetClass.CRYPTO,
        side="buy",
        quantity=2.0,
        algo=ExecutionAlgoConfig(
            algo_type=ExecutionAlgoType.TWAP,
            urgency=ExecutionUrgency.MEDIUM,
            duration_minutes=30,
            slice_interval_seconds=30,
        ),
        paper_mode=True,
        notes="integration",
    )


@pytest.mark.asyncio
async def test_submit_persists_and_round_trips(_mongo):
    """BTC has a demo quote → submit succeeds, arrival > 0, children stored."""
    order = await _demo_order()
    parent = await ENGINE.submit_parent_order("u_it", order)
    assert parent.id
    assert parent.status == ExecutionStatus.FILLED
    assert parent.arrival_price and parent.arrival_price > 0
    assert parent.filled_qty == pytest.approx(2.0, abs=1e-3)
    assert parent.implementation_shortfall_bps is not None
    assert parent.paper_mode is True
    assert len(parent.child_orders) > 1

    fetched = await ENGINE.get_parent_order("u_it", parent.id)
    assert fetched is not None
    assert fetched.id == parent.id
    assert fetched.avg_fill_price == pytest.approx(parent.avg_fill_price, abs=1e-6)


@pytest.mark.asyncio
async def test_list_filters_by_status_and_user(_mongo):
    await ENGINE.submit_parent_order("u_it", await _demo_order())
    await ENGINE.submit_parent_order("u_other", await _demo_order())

    mine = await ENGINE.list_parent_orders("u_it")
    assert len(mine) == 1
    assert all(o.user_id == "u_it" for o in mine)

    filled = await ENGINE.list_parent_orders("u_it", status=ExecutionStatus.FILLED.value)
    assert len(filled) == 1
    cancelled = await ENGINE.list_parent_orders("u_it", status="cancelled")
    assert cancelled == []


@pytest.mark.asyncio
async def test_get_analytics_computes_measured_slice_impact(_mongo):
    parent = await ENGINE.submit_parent_order("u_it", await _demo_order())
    analytics = await ENGINE.get_analytics("u_it", parent.id)
    assert analytics is not None
    assert analytics.parent_id == parent.id
    assert analytics.num_child_orders == len(parent.child_orders)
    assert analytics.arrival_price > 0
    assert analytics.total_fees >= 0
    # Measured max-slice impact must be present once fills have prices.
    assert analytics.max_slice_impact_bps is not None


@pytest.mark.asyncio
async def test_cancel_rejects_filled_order(_mongo):
    parent = await ENGINE.submit_parent_order("u_it", await _demo_order())
    with pytest.raises(ValueError, match="Only queued / working"):
        await ENGINE.cancel_parent_order("u_it", parent.id)


@pytest.mark.asyncio
async def test_unknown_order_cancel_and_get_return_not_found(_mongo):
    assert await ENGINE.get_parent_order("u_it", "nope") is None
    with pytest.raises(ValueError, match="Order not found"):
        await ENGINE.cancel_parent_order("u_it", "nope")


@pytest.mark.asyncio
async def test_analytics_unknown_order_returns_none(_mongo):
    assert await ENGINE.get_analytics("u_it", "nope") is None


@pytest.mark.asyncio
async def test_cancel_queued_order_flips_status(_mongo):
    """Queued/working orders (e.g. from a future live path) must be cancellable."""
    from app.core.database import get_db

    now = datetime.now(UTC)
    doc = {
        "_id": "queued-1",
        "user_id": "u_it",
        "asset": "BTC",
        "asset_class": AssetClass.CRYPTO.value,
        "side": "buy",
        "quantity": 10.0,
        "filled_qty": 0.0,
        "remaining_qty": 10.0,
        "avg_fill_price": None,
        "arrival_price": 100.0,
        "limit_price": None,
        "status": ExecutionStatus.QUEUED.value,
        "algo": {"algo_type": ExecutionAlgoType.TWAP.value, "urgency": ExecutionUrgency.MEDIUM.value},
        "paper_mode": True,
        "strategy_id": None,
        "child_orders": [],
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "implementation_shortfall_bps": None,
        "vwap_deviation_bps": None,
        "notes": None,
        "risk_score_at_submission": None,
        "rejection_reason": None,
    }
    doc["_id"] = "queued-1"
    await get_db().execution_orders.insert_one(doc)

    cancelled = await ENGINE.cancel_parent_order("u_it", "queued-1")
    assert cancelled.status == ExecutionStatus.CANCELLED
    assert cancelled.completed_at is not None
