"""
Phase 2 — Algorithmic Execution Engine models & interfaces.

Phase 1: educational + paper simulation only.
Phase 2: live venue routing under explicit approval + risk gates.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.schemas import AssetClass


class ExecutionAlgoType(str, Enum):
    MARKET = "market"              # immediate cross (small size only)
    TWAP = "twap"
    VWAP = "vwap"
    POV = "pov"
    IMPLEMENTATION_SHORTFALL = "implementation_shortfall"
    ICEBERG = "iceberg"
    ADAPTIVE = "adaptive"
    SOR = "smart_order_router"     # meta-router


class ExecutionUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"   # Phase 2 human/risk gate
    QUEUED = "queued"
    WORKING = "working"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    PAUSED = "paused"
    FAILED = "failed"


class VenueType(str, Enum):
    EXCHANGE = "exchange"
    DARK = "dark"
    DEX = "dex"
    OTC = "otc"
    INTERNAL = "internal"


# ---------- Request / Config ----------

class ExecutionAlgoConfig(BaseModel):
    """Parameters that control how a parent order is sliced."""
    algo_type: ExecutionAlgoType = ExecutionAlgoType.TWAP
    urgency: ExecutionUrgency = ExecutionUrgency.MEDIUM

    # Time / schedule
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = Field(None, ge=1, le=1440)

    # Participation
    target_participation_rate: float | None = Field(None, ge=0.01, le=0.40)  # e.g. 0.10 = 10%
    max_participation_rate: float | None = Field(0.20, ge=0.01, le=0.50)

    # Slicing
    slice_interval_seconds: int = Field(30, ge=5, le=600)
    randomize_slices: bool = True          # anti-gaming
    min_slice_notional: float | None = None
    max_slice_notional: float | None = None

    # Iceberg
    display_qty: float | None = None    # visible tip
    display_qty_pct: float | None = Field(None, ge=0.01, le=0.50)

    # Limits & safeguards
    limit_price: float | None = None
    max_slippage_bps: float | None = Field(50, ge=1, le=500)
    would_price: float | None = None    # do-not-cross beyond this
    allow_dark: bool = True
    allow_dex: bool = False
    preferred_venues: list[str] = []
    excluded_venues: list[str] = []

    # Adaptive / IS
    alpha_signal: float | None = None   # short-term view (-1 to +1)
    risk_aversion: float = Field(0.5, ge=0.0, le=1.0)


class ParentOrderCreate(BaseModel):
    """User or strategy submits a parent order → Execution Engine."""
    asset: str
    asset_class: AssetClass
    side: Literal["buy", "sell"]
    quantity: float = Field(..., gt=0)
    order_type: Literal["limit", "market"] = "limit"
    limit_price: float | None = None

    # Algo choice
    algo: ExecutionAlgoConfig = Field(default_factory=ExecutionAlgoConfig)

    # Risk / compliance context (filled by Risk Engine)
    strategy_id: str | None = None
    paper_mode: bool = True                # Phase 1 always True
    client_order_id: str | None = None
    notes: str | None = None


class ChildOrder(BaseModel):
    """Individual slice sent to a venue."""
    id: str
    parent_id: str
    venue: str
    venue_type: VenueType
    side: str
    quantity: float
    filled_qty: float = 0.0
    avg_price: float | None = None
    limit_price: float | None = None
    status: ExecutionStatus
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    fees: float = 0.0
    raw_response: dict[str, Any] | None = None


class ParentOrder(BaseModel):
    """Full state of a parent (algo) order."""
    id: str
    user_id: str
    asset: str
    asset_class: AssetClass
    side: str
    quantity: float
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    avg_fill_price: float | None = None
    arrival_price: float | None = None      # decision / arrival benchmark
    limit_price: float | None = None
    status: ExecutionStatus
    algo: ExecutionAlgoConfig
    paper_mode: bool = True
    strategy_id: str | None = None
    child_orders: list[ChildOrder] = []
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    implementation_shortfall_bps: float | None = None
    vwap_deviation_bps: float | None = None
    notes: str | None = None
    risk_score_at_submission: float | None = None
    rejection_reason: str | None = None


class ExecutionAnalytics(BaseModel):
    """Post-trade / live analytics for a parent order."""
    parent_id: str
    arrival_price: float
    avg_fill_price: float
    implementation_shortfall_bps: float
    vwap_benchmark: float | None = None
    vwap_deviation_bps: float | None = None
    twap_benchmark: float | None = None
    total_fees: float
    total_notional: float
    fill_ratio: float
    num_child_orders: int
    num_venues: int
    duration_seconds: float | None = None
    participation_rate_realized: float | None = None
    max_slice_impact_bps: float | None = None
    venue_breakdown: list[dict[str, Any]] = []


class ExecutionAlgoInfo(BaseModel):
    """Educational metadata for the research panel."""
    algo_type: ExecutionAlgoType
    name: str
    short_description: str
    how_it_works: str
    best_for: list[str]
    weaknesses: list[str]
    crypto_notes: str
    typical_params: dict[str, Any]
    phase2_ready: bool = True


# ---------- Interface contract (Phase 2 implementors must satisfy) ----------

class ExecutionEngineProtocol:
    """
    Abstract interface. Phase 1 provides a PaperExecutionEngine.
    Phase 2 swaps in LiveExecutionEngine (CCXT / exchange APIs / SOR).
    """

    async def submit_parent_order(self, user_id: str, order: ParentOrderCreate) -> ParentOrder:
        """Risk-checked submission. Returns parent with status."""
        raise NotImplementedError

    async def cancel_parent_order(self, user_id: str, parent_id: str) -> ParentOrder:
        raise NotImplementedError

    async def get_parent_order(self, user_id: str, parent_id: str) -> ParentOrder | None:
        raise NotImplementedError

    async def list_parent_orders(self, user_id: str, status: str | None = None) -> list[ParentOrder]:
        raise NotImplementedError

    async def get_analytics(self, user_id: str, parent_id: str) -> ExecutionAnalytics | None:
        raise NotImplementedError

    async def recommend_algo(
        self,
        asset: str,
        asset_class: AssetClass,
        side: str,
        quantity: float,
        urgency: ExecutionUrgency,
    ) -> ExecutionAlgoConfig:
        """Heuristic recommender used by UI and AI Council."""
        raise NotImplementedError
