"""
Shared Pydantic schemas & enums for hf-market-engine (Phase 1).

Research, simulation and AI-assisted analysis only.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

# ---------- Enums ----------

class AssetClass(str, Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    ETF = "etf"
    FOREX = "forex"
    MACRO = "macro"
    DEFI = "defi"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalType(str, Enum):
    MOMENTUM_BREAKOUT = "momentum_breakout"
    CRYPTO_STOCK_SYMPATHY = "crypto_stock_sympathy"
    CORRELATION_DIVERGENCE = "correlation_divergence"
    RISK_OFF_WARNING = "risk_off_warning"
    MEAN_REVERSION = "mean_reversion"
    LIQUIDITY_WARNING = "liquidity_warning"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


# ---------- Auth ----------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str | None = None


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    plan: str = "free"
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Market ----------

class PriceQuote(BaseModel):
    symbol: str
    name: str
    price: float
    asset_class: AssetClass
    change_24h: float | None = None
    change_7d: float | None = None
    change_30d: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    source: str = "demo"
    provider: str = ""
    observed_at: datetime | None = None
    freshness_seconds: int | None = None
    last_updated: datetime | None = None


class MarketOverview(BaseModel):
    regime: str = "mixed"
    regime_confidence: float = 0.0
    btc: PriceQuote | None = None
    eth: PriceQuote | None = None
    total_market_cap: float | None = None
    total_volume_24h: float | None = None
    btc_dominance: float | None = None
    last_updated: datetime | None = None


class TradeIdea(BaseModel):
    id: str
    asset: str
    asset_class: AssetClass
    direction: SignalDirection
    thesis: str
    signal_type: SignalType
    confidence: float = Field(..., ge=0, le=100)
    time_horizon: str
    correlation_context: str | None = None
    macro_context: str | None = None
    risk_score: float = Field(..., ge=0, le=100)
    invalidation: str | None = None
    paper_trade_setup: str | None = None
    supporting_indicators: list[str] = []
    disclaimer: str = "Research only, not financial advice."


class CorrelationPair(BaseModel):
    pair: str
    asset_a: str
    asset_b: str
    correlation: float = Field(..., ge=-1, le=1)
    relationship_type: str
    status: str
    ai_explanation: str | None = None
    risk_warning: str | None = None


# ---------- Strategies / Backtest ----------

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    asset: str = "BTC"
    asset_class: AssetClass = AssetClass.CRYPTO
    timeframe: str = "1h"
    entry_condition: str | None = None
    exit_condition: str | None = None
    stop_loss_pct: float = 2.5
    take_profit_pct: float = 6.0
    max_position_pct: float = 5.0
    max_daily_loss_pct: float = 3.0
    market_regime_filter: bool = False
    notes: str | None = None


class StrategyOut(BaseModel):
    id: str
    user_id: str
    name: str
    asset: str
    asset_class: AssetClass
    timeframe: str
    entry_condition: str | None = None
    exit_condition: str | None = None
    stop_loss_pct: float
    take_profit_pct: float
    max_position_pct: float
    max_daily_loss_pct: float
    market_regime_filter: bool = False
    notes: str | None = None
    created_at: datetime


class BacktestRequest(BaseModel):
    strategy: StrategyCreate | None = None
    initial_capital: float = 10000.0


class BacktestResult(BaseModel):
    id: str
    strategy_name: str
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    profit_factor: float
    average_trade_pct: float
    number_of_trades: int
    best_trade_pct: float
    worst_trade_pct: float
    equity_curve: list[dict[str, Any]] = []
    overfit_risk_score: float
    ai_review: str
    is_simulated: bool = True


# ---------- Paper Trading ----------

class PaperTradeCreate(BaseModel):
    asset: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO
    direction: Literal["long", "short"] = "long"
    quantity: float = Field(..., gt=0)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    notes: str | None = None
    strategy_id: str | None = None


class PaperTradeOut(BaseModel):
    id: str
    user_id: str
    asset: str
    asset_class: AssetClass
    direction: str
    quantity: float
    entry_price: float
    current_price: float | None = None
    exit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    status: str
    notes: str | None = None
    strategy_id: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    ai_review: str | None = None


# ---------- Risk ----------

class RiskReview(BaseModel):
    score: float = Field(..., ge=0, le=100)
    level: RiskLevel
    main_factors: list[str] = []
    suggested_mitigation: list[str] = []
    trade_blocked: bool = False
    regime_warning: str | None = None


# ---------- Portfolio ----------

class HoldingCreate(BaseModel):
    asset: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO
    quantity: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    notes: str | None = None


class HoldingOut(BaseModel):
    id: str
    user_id: str
    asset: str
    asset_class: AssetClass
    quantity: float
    entry_price: float
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    allocation_pct: float | None = None
    notes: str | None = None
    created_at: datetime


# ---------- Watchlist ----------

class WatchlistItemCreate(BaseModel):
    symbol: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO


class WatchlistItemOut(BaseModel):
    id: str
    symbol: str
    asset_class: AssetClass
    price: float | None = None
    change_24h: float | None = None
    change_7d: float | None = None
    volume: float | None = None
    added_at: datetime


# ---------- System ----------

class SystemHealth(BaseModel):
    status: str
    api: str = "ok"
    database: str
    coingecko: str = "unknown"
    ai: str = "template"
    ai_model: str = ""
    market_data_mode: str = "demo"
    auth: str = "ok"
    last_market_refresh: datetime | None = None
    active_users: int = 0
    saved_strategies: int = 0
    paper_trades: int = 0


class PlanInfo(BaseModel):
    id: str
    name: str
    price_monthly: int
    setup_fee: int | None = None
    features: list[str] = []
    ai_reviews_per_month: int = 0
    max_watchlist: int = 10
    seats: int | None = None


# ---------- Mining Intelligence ----------

class AsicModelInfo(BaseModel):
    model: str
    name: str
    hashrate_ths: float
    power_watts: float
    price_usd: float
    efficiency_j_per_ths: float | None = None
    class_: str | None = Field(default=None, alias="class")


class MiningNetworkData(BaseModel):
    provider: str
    source: str
    observed_at: datetime
    hashrate_ths: float
    difficulty: float
    block_subsidy: float
    block_time_seconds: float
    expected_blocks_per_day: float


class MiningEstimateRequest(BaseModel):
    asic_model: str | None = None
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    btc_price: float | None = Field(default=None, gt=0)


class MiningEstimateResult(BaseModel):
    simulation: bool
    available: bool = True
    reason: str | None = None
    asic: dict[str, Any]
    btc_price: float
    btc_price_provider: str
    network: MiningNetworkData
    estimates: dict[str, Any]
    ai_review: str | None = None
    receipt_id: str | None = None


class MineVsBuyRequest(BaseModel):
    capital_usd: float = Field(gt=0)
    asic_model: str
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    horizon_days: int = Field(ge=1, le=3650, default=365)
    difficulty_growth_pct_year: float = Field(default=20.0)
    btc_price_at_horizon: float | None = Field(default=None, gt=0)
    setup_cost_usd_per_unit: float = Field(ge=0, default=0.0)
    hosting_cost_usd_per_unit_month: float = Field(ge=0, default=0.0)
    maintenance_cost_usd_per_unit_month: float = Field(ge=0, default=0.0)
    hardware_resale_value_usd_per_unit: float = Field(ge=0, default=0.0)


class MineVsBuyResult(BaseModel):
    simulation: bool
    asic: dict[str, Any]
    observed: dict[str, Any]
    assumptions: dict[str, Any]
    buy_path: dict[str, Any]
    mining_path: dict[str, Any]
    break_even_price_at_horizon: float | None = None
    verdict: str | None = None
    ai_review: str | None = None
    receipt_id: str | None = None


class MiningScenarioRequest(BaseModel):
    asic_model: str | None = None
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    price_shifts_pct: list[float] = Field(default_factory=lambda: [-50, -25, -10, 0, 10, 25, 50])
    difficulty_shifts_pct: list[float] = Field(default_factory=lambda: [-10, 0, 10, 25])


class MiningScenarioResult(BaseModel):
    simulation: bool
    network: MiningNetworkData
    scenarios: list[dict[str, Any]]
    receipt_id: str | None = None


class MiningFleetRequest(BaseModel):
    units: int = Field(gt=0, le=10000)
    asic_model: str | None = None
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)


class MiningFleetResult(BaseModel):
    simulation: bool
    network: MiningNetworkData
    asic: dict[str, Any]
    estimates: dict[str, Any]
    receipt_id: str | None = None


# ---------- Institutional Decision Layer ----------

class ScenarioPreset(BaseModel):
    name: str
    label: str
    vector: dict[str, float]


class ScenarioVector(BaseModel):
    btc_price_shift_pct: float = 0.0
    difficulty_shift_pct: float = 0.0
    electricity_usd_kwh: float | None = None
    uptime_pct: float | None = None
    label: str | None = None


class ScenarioRunRequest(BaseModel):
    asic_model: str | None = None
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    preset_names: list[str] = Field(default_factory=list)
    scenarios: list[ScenarioVector] = Field(default_factory=list)
    max_total: int = Field(gt=0, le=50, default=20)


class ScenarioRunResultItem(BaseModel):
    label: str
    vector: dict[str, float]
    btc_price: float
    difficulty: float
    estimates: dict[str, Any]
    risk: str
    risk_flags: list[str]


class ScenarioRunResult(BaseModel):
    simulation: bool
    btc_price: float
    btc_price_provider: str
    network: MiningNetworkData
    asic: dict[str, Any]
    scenarios: list[ScenarioRunResultItem]
    ai_review: str | None = None
    receipt_id: str | None = None


class AllocationRequest(BaseModel):
    capital_usd: float = Field(gt=0)
    available_mw: float = Field(ge=0, default=0.0)
    asic_model: str | None = None
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    energy_sell_price_usd_kwh: float = Field(ge=0, default=0.05)
    cash_interest_rate_pct_year: float = Field(ge=0, default=4.0)
    gpu_model: str | None = None
    gpu_capex_usd: float | None = Field(gt=0, default=None)
    gpu_power_kw: float | None = Field(gt=0, default=None)
    gpu_cloud_rental_usd_per_hr: float | None = Field(gt=0, default=None)
    gpu_rental_usd_per_hr: float | None = Field(gt=0, default=None)
    gpu_utilization_pct: float = Field(gt=0, le=100, default=85.0)
    gpu_uptime_pct: float = Field(gt=0, le=100, default=100.0)
    gpu_units_cap: int = Field(gt=0, default=256)


class AllocationOption(BaseModel):
    key: str
    label: str
    available: bool
    reason: str | None = None
    capital_deployed: float
    capital_left: float
    power_used_mw: float
    btc_exposure: float
    flow_day: float
    flow_month: float
    flow_unit: str
    break_even: float | None = None
    risk_flags: list[str]
    observed: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    payback_days: float | None = None
    capital_basis_usd: float | None = None


class AllocationResult(BaseModel):
    simulation: bool
    capital_usd: float
    available_mw: float
    btc_price: float
    btc_price_provider: str
    network: MiningNetworkData
    asic: dict[str, Any]
    options: list[AllocationOption]
    ranking: list[str]
    ranking_basis: str
    ai_review: str | None = None
    receipt_id: str | None = None


class GpuEconomicsRequest(BaseModel):
    gpu_model: str | None = None
    gpu_capex_usd: float | None = Field(gt=0, default=None)
    gpu_power_kw: float | None = Field(gt=0, default=None)
    gpu_cloud_rental_usd_per_hr: float | None = Field(gt=0, default=None)
    gpu_rental_usd_per_hr: float | None = Field(gt=0, default=None)
    electricity_usd_kwh: float = Field(gt=0, default=0.10)
    gpu_utilization_pct: float = Field(gt=0, le=100, default=85.0)
    gpu_uptime_pct: float = Field(gt=0, le=100, default=100.0)
    capital_usd: float = Field(gt=0)
    available_mw: float = Field(ge=0, default=0.0)
    gpu_units_cap: int = Field(gt=0, default=256)


class GpuLaneResult(BaseModel):
    key: str
    label: str
    available: bool
    reason: str | None = None
    units: int = 0
    capital_deployed: float = 0.0
    power_used_mw: float = 0.0
    flow_day: float = 0.0
    flow_month: float = 0.0
    flow_unit: str = "usd_month_operating"
    payback_days: float | None = None
    per_unit: dict[str, Any] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class GpuEconomicsResult(BaseModel):
    gpu: dict[str, Any]
    build: GpuLaneResult
    cloud: GpuLaneResult
    ai_review: str | None = None
    receipt_id: str | None = None


class CapitalRunRequest(BaseModel):
    capital_usd: float = Field(gt=0)
    available_mw: float = Field(ge=0, default=0.0)
    horizon_months: int = Field(gt=0, le=60, default=12)
    electricity_usd_kwh: float = Field(gt=0, default=0.06)
    risk_profile: str = Field(default="balanced")
    btc_price: float | None = Field(default=None, gt=0)
    btc_price_at_horizon: float | None = Field(default=None, gt=0)
    difficulty_growth_pct_year: float = Field(ge=0, default=20.0)
    asic_model: str | None = Field(default=None)
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    pool_fee_pct: float = Field(ge=0, default=1.0)
    uptime_pct: float = Field(gt=0, le=100, default=95.0)
    setup_cost_usd_per_unit: float = Field(ge=0, default=0.0)
    hosting_cost_usd_per_unit_month: float = Field(ge=0, default=0.0)
    maintenance_cost_usd_per_unit_month: float = Field(ge=0, default=0.0)
    hardware_resale_value_usd_per_unit: float = Field(ge=0, default=0.0)
    gpu_model: str | None = Field(default=None)
    gpu_capex_usd: float | None = Field(default=None, gt=0)
    gpu_power_kw: float | None = Field(default=None, gt=0)
    gpu_cloud_rental_usd_per_hr: float | None = Field(default=None, gt=0)
    gpu_rental_usd_per_hr: float | None = Field(default=None, gt=0)
    gpu_utilization_pct: float = Field(gt=0, le=100, default=85.0)
    gpu_uptime_pct: float = Field(gt=0, le=100, default=100.0)
    gpu_units_cap: int = Field(gt=0, default=256)
    gpu_pue: float = Field(ge=1.0, default=1.3)
    energy_acquisition_usd_kwh: float | None = Field(default=None, gt=0)
    energy_sell_price_usd_kwh: float | None = Field(default=None, gt=0)
    energy_utilization_pct: float = Field(gt=0, le=100, default=100.0)
    storage_mwh: float = Field(ge=0, default=0.0)
    storage_capex_usd_per_mwh: float = Field(ge=0, default=0.0)
    storage_roundtrip_pct: float = Field(gt=0, le=100, default=85.0)
    cash_interest_rate_pct_year: float = Field(ge=0, default=4.0)


class CapitalRunResult(BaseModel):
    simulation: bool
    inputs: dict[str, Any]
    observed: dict[str, Any]
    lanes: dict[str, Any]
    ranking: list[str]
    ranking_basis: str
    recommendation: dict[str, Any]
    ai_review: str | None = None
    receipt_id: str | None = None


class CapitalScenarioRequest(BaseModel):
    run: CapitalRunRequest
    vectors: list[str] | None = None


class CapitalScenarioRow(BaseModel):
    label: str
    vector: dict[str, Any]
    btc_price: float | None = None
    difficulty: float | None = None
    lanes: dict[str, Any]


class CapitalScenarioResult(BaseModel):
    base: dict[str, Any]
    matrix: list[CapitalScenarioRow]
    scenario_keys: list[str]
    disclaimer: str
    receipt_id: str | None = None


class CapitalOptimizeRequest(BaseModel):
    capital_usd: float = Field(gt=0)
    available_mw: float = Field(ge=0, default=0.0)
    horizon_months: int = Field(gt=0, le=60, default=12)
    electricity_usd_kwh: float = Field(gt=0, default=0.06)
    asic_model: str | None = Field(default=None)
    hashrate_ths: float | None = None
    power_watts: float | None = None
    hardware_cost_usd: float | None = None
    risk_profiles: list[str] = Field(default_factory=lambda: ["conservative", "balanced", "aggressive"])


class CapitalOptimizeResult(BaseModel):
    base: dict[str, Any]
    proposals: dict[str, Any]
    disclaimer: str
    receipt_id: str | None = None
