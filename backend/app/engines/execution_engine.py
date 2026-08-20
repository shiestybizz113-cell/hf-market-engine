"""
Paper Execution Engine (Phase 1) — simulated slices + slippage.

Never touches a real venue. Educational + paper simulation only.
Phase 2 swaps in LiveExecutionEngine (CCXT / exchange APIs / SOR)
behind the same ExecutionEngineProtocol.
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.core.config import settings
from app.core.database import get_db
from app.models.schemas import AssetClass
from app.models.execution import (
    ExecutionEngineProtocol,
    ParentOrderCreate,
    ParentOrder,
    ChildOrder,
    ExecutionAlgoConfig,
    ExecutionAlgoInfo,
    ExecutionAlgoType,
    ExecutionUrgency,
    ExecutionStatus,
    ExecutionAnalytics,
    VenueType,
)
from app.engines.journal_engine import journal_engine


ALGO_CATALOG: List[ExecutionAlgoInfo] = [
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.MARKET,
        name="Market — Immediate Cross",
        short_description=(
            "Cross the entire order in one go at the prevailing bid/offer. "
            "Simplest and fastest, but pays the full spread and all impact."
        ),
        how_it_works=(
            "The parent order is submitted as a single child order executed immediately "
            "against resting liquidity. Guarantees execution but typically fills inside the "
            "spread-adjusted midpoint, making it the most expensive option for large size."
        ),
        best_for=["Small size", "High urgency", "Closing a position quickly"],
        weaknesses=["Maximum market impact", "Pays full spread", "Reveals intent"],
        crypto_notes=(
            "On CEXs, market orders sweep the top of the book. On DEXs a market order is "
            "a swap at the AMM price — always worse than a limit when patience allows."
        ),
        typical_params={"max_notional": "0.1% of ADV", "urgency": "high/critical"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.TWAP,
        name="TWAP — Time-Weighted Average Price",
        short_description=(
            "Split the order into equal-size slices across the trading window to "
            "reduce timing risk and market impact."
        ),
        how_it_works=(
            "The window (e.g. 30–120 min) is divided into fixed intervals. Each interval "
            "submits a slice of roughly equal notional, optionally randomized to avoid "
            "predictable patterns. TWAP does not adapt to volume."
        ),
        best_for=["Large size with no urgency", "Low-volume pairs", "Baseline execution"],
        weaknesses=["Ignores volume", "Slow to react to regime", "Slippage in thin books"],
        crypto_notes=(
            "Crypto trades 24/7, so the window is absolute time, not session-relative. "
            "Use calibrated TWAP sized against rolling ADV for the symbol."
        ),
        typical_params={"window": "30–120 min", "slice_interval": "30–60s",
                        "randomize": "on", "max_participation": "10–20%"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.VWAP,
        name="VWAP — Volume-Weighted Average Price",
        short_description=(
            "Distribute slices in proportion to expected volume so the average fill "
            "tracks the session's volume-weighted price benchmark."
        ),
        how_it_works=(
            "Expected volume curves (from history + real-time flow) weight each slice. "
            "Because volume varies across the day, slices are smaller in quiet periods "
            "and larger in active periods."
        ),
        best_for=["Benchmark-sensitive mandates", "Equity block trades", "Report vs VWAP"],
        weaknesses=["Needs volume forecasts", "Underperforms when forecast is wrong"],
        crypto_notes=(
            "No official VWAP on most CEXs; institutional participants use a rolling "
            "24h VWAP proxy. Execution firms provide it as a value-added benchmark."
        ),
        typical_params={"window": "full day or window", "volume_curve": "historical + realtime",
                        "max_participation": "5–20%"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.POV,
        name="POV — Percentage of Volume",
        short_description=(
            "Join the market at a target participation rate — buy a fixed percentage of "
            "observed volume so you never dominate the tape."
        ),
        how_it_works=(
            "Real-time volume (trades or prints) is sampled; each slice is sized to a "
            "target participation rate (e.g. 10%). If volume dries up, slicing slows; "
            "if volume explodes, slicing accelerates."
        ),
        best_for=["Avoiding market impact", "Liquid markets", "Stealth accumulation"],
        weaknesses=["Duration is unknown", "Slow in low volume", "Needs reliable tape"],
        crypto_notes=(
            "Good for DEX/CEX accumulation. Use reported trade volume (not just top-of-book "
            "liquidity) to size participation."
        ),
        typical_params={"target_participation": "5–15%", "max_participation": "20–40%",
                        "slice_interval": "15–60s"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.IMPLEMENTATION_SHORTFALL,
        name="IS — Implementation Shortfall",
        short_description=(
            "Minimize total cost: spread + market impact + opportunity cost + delay, "
            "balanced against your urgency and a short-term alpha signal."
        ),
        how_it_works=(
            "Arrival price is the benchmark. The optimizer chooses how aggressively to "
            "trade each slice by trading off expected impact now versus risk of the price "
            "moving against you. More urgency → trade faster even at higher impact."
        ),
        best_for=["Signal-driven orders", "When alpha decays fast", "Institutional desks"],
        weaknesses=["Most complex", "Requires impact model", "Hard to explain"],
        crypto_notes=(
            "A short-term directional view (your alpha_signal) can bias the schedule: "
            "buy faster if you expect strength, slower if you expect a dip."
        ),
        typical_params={"urgency": "low/medium/high/critical", "impact_model": "square-root law",
                        "alpha_signal": "-1 to +1", "risk_aversion": "0–1"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.ICEBERG,
        name="Iceberg — Hidden Liquidity Slicing",
        short_description=(
            "Expose only a small display quantity at a time while the rest of the order "
            "sits hidden, refilling as each tip fills. Minimizes information leakage."
        ),
        how_it_works=(
            "A visible tip (display_qty) is posted at a limit. When it fills, another tip "
            "is posted, and so on, until the full parent quantity is done."
        ),
        best_for=["Large passive orders", "Narrow books", "Reducing information leakage"],
        weaknesses=["Passive risk", "Adverse selection", "Slow in fast markets"],
        crypto_notes=(
            "CEX order books show the tip; sophisticated participants detect icebergs via "
            "fill-rate / refill patterns, so randomize tip size and price placement."
        ),
        typical_params={"display_qty": "5–10% of order", "limit_price": "mid or better",
                        "randomize_tip": "on"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.ADAPTIVE,
        name="Adaptive — Regime-Aware Slicing",
        short_description=(
            "Dynamically adjust aggressiveness based on live volatility, spread, and "
            "liquidity so the schedule stays efficient as conditions change."
        ),
        how_it_works=(
            "A control loop reads market state (spread width, realized vol, book depth, "
            "momentum) and dials the slice aggressiveness up or down within hard limits."
        ),
        best_for=["Volatile markets", "Multi-hour schedules", "Hands-off execution"],
        weaknesses=["More parameters", "Needs good market data", "Backtest-dependent"],
        crypto_notes=(
            "Crypto vol regimes shift fast (funding spikes, liquidation cascades). Adaptive "
            "slicing is the natural fit for 24/7 markets with erratic liquidity."
        ),
        typical_params={"vol_floor/ceil": "bps bands", "spread_threshold": "e.g. 3 bps",
                        "participation_range": "5–25%"},
        phase2_ready=True,
    ),
    ExecutionAlgoInfo(
        algo_type=ExecutionAlgoType.SOR,
        name="Smart Order Router",
        short_description=(
            "A meta-router that routes each child order across venues (CEXs, DEXs, dark "
            "pools, OTC) to capture the best available liquidity and price."
        ),
        how_it_works=(
            "Venue inventory (prices, fees, depth, latency) is scored per child order. "
            "Orders route to the cheapest venue that can satisfy the slice within "
            "slippage limits, falling back if venues fail."
        ),
        best_for=["Fragmented liquidity", "Multi-venue crypto", "Fee optimization"],
        weaknesses=["Needs venue data", "Complex failure handling"],
        crypto_notes=(
            "Crypto liquidity is split across dozens of CEXs and DEXs. SOR is what makes "
            "a crypto algo genuinely competitive — route to the venue with the best "
            "all-in price (price + fees + estimated impact)."
        ),
        typical_params={"venue_score": "price + fee + depth", "fallback": "next-best venue",
                        "min_save": "threshold in bps to switch venue"},
        phase2_ready=True,
    ),
]


class PaperExecutionEngine(ExecutionEngineProtocol):
    """Phase 1 — deterministic-ish simulated fills, zero real risk."""

    async def submit_parent_order(self, user_id: str, order: ParentOrderCreate) -> ParentOrder:
        if not order.paper_mode:
            raise ValueError("Live execution disabled in Phase 1 — paper_mode must be True")

        db = get_db()
        now = datetime.now(timezone.utc)

        # Resolve arrival price from market data (or a plausible default).
        from app.services.market_data import market_data_service
        quote = await market_data_service.get_quote(order.asset, order.asset_class)
        arrival = quote.price if quote else 100.0

        parent_id = str(uuid.uuid4())
        impact_ctx = self._impact_context(quote)
        children = await self._simulate_children(order, arrival, parent_id, now, impact_ctx)

        total_filled = sum(c.filled_qty for c in children)
        notional = sum(c.filled_qty * (c.avg_price or arrival) for c in children)
        avg_fill = (notional / total_filled) if total_filled > 0 else arrival

        shortfall_bps = round((avg_fill - arrival) / arrival * 10000 * (1 if order.side == "buy" else -1), 2)

        status = ExecutionStatus.FILLED
        parent = ParentOrder(
            id=parent_id,
            user_id=user_id,
            asset=order.asset.upper(),
            asset_class=order.asset_class,
            side=order.side,
            quantity=order.quantity,
            filled_qty=total_filled,
            remaining_qty=round(order.quantity - total_filled, 6),
            avg_fill_price=round(avg_fill, 6),
            arrival_price=round(arrival, 6),
            limit_price=order.limit_price,
            status=status,
            algo=order.algo,
            paper_mode=True,
            strategy_id=order.strategy_id,
            child_orders=children,
            created_at=now,
            started_at=now,
            completed_at=now,
            implementation_shortfall_bps=shortfall_bps,
            vwap_deviation_bps=None,
            notes=order.notes,
            risk_score_at_submission=None,
        )

        doc = parent.model_dump(mode="json")
        doc["_id"] = parent_id
        await db.execution_orders.insert_one(doc)

        try:
            await journal_engine.auto_from_execution(user_id, doc)
        except Exception:
            pass

        return parent

    # ------------------------------------------------------------------
    # Impact model integration
    # ------------------------------------------------------------------

    @staticmethod
    def _impact_context(quote) -> dict:
        """Extract ADV and volatility from a market quote for the impact model."""
        if quote is None:
            return {"adv": None, "sigma_daily": None}
        adv = getattr(quote, "volume_24h", None)
        high = getattr(quote, "high_24h", None)
        low = getattr(quote, "low_24h", None)
        sigma_daily = None
        if high is not None and low is not None:
            from app.services.market_impact import parkinson_sigma
            sigma_daily = parkinson_sigma(high, low)
        return {"adv": adv, "sigma_daily": sigma_daily}

    @staticmethod
    def _slice_impact_bps(
        slice_qty: float,
        total_qty: float,
        order,
        ctx: dict,
    ) -> float:
        """Return impact in bps for a single slice, or 0.0 when unavailable."""
        mode = settings.IMPACT_MODEL

        if mode == "none":
            return 0.0

        if mode == "legacy_random":
            return random.uniform(0.5, 4.0) + (slice_qty / max(total_qty, 1e-9)) * random.uniform(0.5, 3.0)

        # sqrt_law_v1
        adv = ctx.get("adv")
        sigma_daily = ctx.get("sigma_daily")
        if adv is None or sigma_daily is None:
            return 0.0
        notional = slice_qty  # unitless ratio, same as qty for paper
        from app.services.market_impact import estimate_impact
        est = estimate_impact(notional, adv, sigma_daily=sigma_daily)
        if est.impact_bps is None:
            return 0.0
        return est.impact_bps

    async def _simulate_children(
        self, order: ParentOrderCreate, arrival: float, parent_id: str, now: datetime,
        impact_ctx: Optional[dict] = None,
    ) -> List[ChildOrder]:
        algo = order.algo.algo_type
        n = self._slice_count(algo, order.quantity, order.algo)
        remaining = order.quantity
        children: List[ChildOrder] = []
        fee_bps = 0.05  # typical taker fee in bps

        for i in range(n):
            if remaining <= 1e-9:
                break
            slice_qty = self._slice_size(algo, order.quantity, n, i)
            slice_qty = min(slice_qty, remaining)

            impact_bps = self._slice_impact_bps(slice_qty, order.quantity, order, impact_ctx or {})
            side_dir = 1 if order.side == "buy" else -1
            fill_price = arrival * (1 + side_dir * impact_bps / 10000)
            if order.limit_price:
                fill_price = min(fill_price, order.limit_price) if order.side == "buy" else max(fill_price, order.limit_price)

            submitted = now + timedelta(seconds=i * order.algo.slice_interval_seconds)
            children.append(ChildOrder(
                id=str(uuid.uuid4()),
                parent_id=parent_id,
                venue=random.choice(["exchange-primary", "exchange-secondary", "dex-aggregator", "dark-pool"]),
                venue_type=random.choice([VenueType.EXCHANGE, VenueType.EXCHANGE, VenueType.DEX, VenueType.DARK]),
                side=order.side,
                quantity=round(slice_qty, 6),
                filled_qty=round(slice_qty, 6),
                avg_price=round(fill_price, 6),
                limit_price=order.limit_price,
                status=ExecutionStatus.FILLED,
                submitted_at=submitted,
                filled_at=submitted + timedelta(seconds=random.uniform(0.2, 8)),
                fees=round(slice_qty * fill_price * fee_bps / 10000, 6),
            ))
            remaining -= slice_qty

        return children

    def _slice_count(self, algo: ExecutionAlgoType, qty: float, cfg: ExecutionAlgoConfig) -> int:
        if algo == ExecutionAlgoType.MARKET:
            return 1
        if cfg.duration_minutes:
            est = cfg.duration_minutes * 60 // cfg.slice_interval_seconds
            return max(2, min(est, 60))
        if qty >= 100:
            return random.randint(12, 24)
        return random.randint(4, 10)

    def _slice_size(self, algo: ExecutionAlgoType, total: float, n: int, i: int) -> float:
        if algo in (ExecutionAlgoType.VWAP, ExecutionAlgoType.POV, ExecutionAlgoType.ADAPTIVE):
            weight = random.uniform(0.4, 1.6)
        else:
            weight = 1.0
        base = total / n
        return base * weight

    async def cancel_parent_order(self, user_id: str, parent_id: str) -> ParentOrder:
        db = get_db()
        doc = await db.execution_orders.find_one({"_id": parent_id, "user_id": user_id})
        if not doc:
            raise ValueError("Order not found")
        if doc.get("status") not in (ExecutionStatus.QUEUED.value, ExecutionStatus.WORKING.value,
                                     ExecutionStatus.PENDING_APPROVAL.value):
            raise ValueError("Only queued / working orders can be cancelled")
        await db.execution_orders.update_one(
            {"_id": parent_id},
            {"$set": {"status": ExecutionStatus.CANCELLED.value, "completed_at": datetime.now(timezone.utc)}},
        )
        doc["status"] = ExecutionStatus.CANCELLED.value
        return self._to_model(doc)

    async def get_parent_order(self, user_id: str, parent_id: str) -> Optional[ParentOrder]:
        db = get_db()
        doc = await db.execution_orders.find_one({"_id": parent_id, "user_id": user_id})
        return self._to_model(doc) if doc else None

    async def list_parent_orders(self, user_id: str, status: Optional[str] = None) -> List[ParentOrder]:
        db = get_db()
        query: dict = {"user_id": user_id}
        if status:
            query["status"] = status
        cursor = db.execution_orders.find(query).sort("created_at", -1).limit(100)
        return [self._to_model(doc) async for doc in cursor]

    async def get_analytics(self, user_id: str, parent_id: str) -> Optional[ExecutionAnalytics]:
        db = get_db()
        doc = await db.execution_orders.find_one({"_id": parent_id, "user_id": user_id})
        if not doc:
            return None
        childs = doc.get("child_orders", [])
        total_fees = round(sum(float(c.get("fees", 0)) for c in childs), 6)
        arrival = float(doc.get("arrival_price") or 0)
        avg = float(doc.get("avg_fill_price") or arrival)
        return ExecutionAnalytics(
            parent_id=parent_id,
            arrival_price=arrival,
            avg_fill_price=avg,
            implementation_shortfall_bps=float(doc.get("implementation_shortfall_bps") or 0),
            vwap_benchmark=None,
            vwap_deviation_bps=doc.get("vwap_deviation_bps"),
            total_fees=total_fees,
            total_notional=avg * float(doc.get("filled_qty") or 0),
            fill_ratio=(float(doc.get("filled_qty") or 0) / float(doc.get("quantity") or 1)),
            num_child_orders=len(childs),
            num_venues=len({c.get("venue") for c in childs}),
            duration_seconds=None,
            participation_rate_realized=None,
            max_slice_impact_bps=None,
            venue_breakdown=[],
        )

    async def recommend_algo(
        self,
        asset: str,
        asset_class: AssetClass,
        side: str,
        quantity: float,
        urgency: ExecutionUrgency,
    ) -> ExecutionAlgoConfig:
        base = ExecutionAlgoConfig()
        if urgency == ExecutionUrgency.CRITICAL or quantity <= 1:
            base.algo_type = ExecutionAlgoType.MARKET
            base.urgency = urgency
            base.duration_minutes = 5
        elif urgency == ExecutionUrgency.HIGH:
            base.algo_type = ExecutionAlgoType.IMPLEMENTATION_SHORTFALL
            base.urgency = urgency
            base.duration_minutes = 30
            base.alpha_signal = 0.3
        elif urgency == ExecutionUrgency.LOW:
            base.algo_type = ExecutionAlgoType.TWAP
            base.urgency = urgency
            base.duration_minutes = 90
        else:
            base.algo_type = ExecutionAlgoType.ADAPTIVE
            base.urgency = urgency
            base.duration_minutes = 60
        return base

    def _to_model(self, doc: dict) -> ParentOrder:
        algo_cfg = ExecutionAlgoConfig(**doc.get("algo", {})) if doc.get("algo") else ExecutionAlgoConfig()
        children = [ChildOrder(**c) for c in doc.get("child_orders", [])]
        return ParentOrder(
            id=doc["_id"],
            user_id=doc["user_id"],
            asset=doc["asset"],
            asset_class=AssetClass(doc["asset_class"]),
            side=doc["side"],
            quantity=doc["quantity"],
            filled_qty=doc.get("filled_qty", 0),
            remaining_qty=doc.get("remaining_qty", 0),
            avg_fill_price=doc.get("avg_fill_price"),
            arrival_price=doc.get("arrival_price"),
            limit_price=doc.get("limit_price"),
            status=ExecutionStatus(doc["status"]),
            algo=algo_cfg,
            paper_mode=doc.get("paper_mode", True),
            strategy_id=doc.get("strategy_id"),
            child_orders=children,
            created_at=doc["created_at"],
            started_at=doc.get("started_at"),
            completed_at=doc.get("completed_at"),
            implementation_shortfall_bps=doc.get("implementation_shortfall_bps"),
            vwap_deviation_bps=doc.get("vwap_deviation_bps"),
            notes=doc.get("notes"),
            risk_score_at_submission=doc.get("risk_score_at_submission"),
            rejection_reason=doc.get("rejection_reason"),
        )


execution_engine = PaperExecutionEngine()
