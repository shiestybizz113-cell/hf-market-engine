"""
Shared Pydantic schemas & enums for hf-market-engine (Phase 1).

Research, simulation and AI-assisted analysis only.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


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
    full_name: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
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
    change_24h: Optional[float] = None
    change_7d: Optional[float] = None
    change_30d: Optional[float] = None
    volume_24h: Optional[float] = None
    market_cap: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    source: str = "demo"
    last_updated: Optional[datetime] = None


class MarketOverview(BaseModel):
    regime: str = "mixed"
    regime_confidence: float = 0.0
    btc: Optional[PriceQuote] = None
    eth: Optional[PriceQuote] = None
    total_market_cap: Optional[float] = None
    total_volume_24h: Optional[float] = None
    btc_dominance: Optional[float] = None
    last_updated: Optional[datetime] = None


class TradeIdea(BaseModel):
    id: str
    asset: str
    asset_class: AssetClass
    direction: SignalDirection
    thesis: str
    signal_type: SignalType
    confidence: float = Field(..., ge=0, le=100)
    time_horizon: str
    correlation_context: Optional[str] = None
    macro_context: Optional[str] = None
    risk_score: float = Field(..., ge=0, le=100)
    invalidation: Optional[str] = None
    paper_trade_setup: Optional[str] = None
    supporting_indicators: List[str] = []
    disclaimer: str = "Research only, not financial advice."


class CorrelationPair(BaseModel):
    pair: str
    asset_a: str
    asset_b: str
    correlation: float = Field(..., ge=-1, le=1)
    relationship_type: str
    status: str
    ai_explanation: Optional[str] = None
    risk_warning: Optional[str] = None


# ---------- Strategies / Backtest ----------

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    asset: str = "BTC"
    asset_class: AssetClass = AssetClass.CRYPTO
    timeframe: str = "1h"
    entry_condition: Optional[str] = None
    exit_condition: Optional[str] = None
    stop_loss_pct: float = 2.5
    take_profit_pct: float = 6.0
    max_position_pct: float = 5.0
    max_daily_loss_pct: float = 3.0
    market_regime_filter: bool = False
    notes: Optional[str] = None


class StrategyOut(BaseModel):
    id: str
    user_id: str
    name: str
    asset: str
    asset_class: AssetClass
    timeframe: str
    entry_condition: Optional[str] = None
    exit_condition: Optional[str] = None
    stop_loss_pct: float
    take_profit_pct: float
    max_position_pct: float
    max_daily_loss_pct: float
    market_regime_filter: bool = False
    notes: Optional[str] = None
    created_at: datetime


class BacktestRequest(BaseModel):
    strategy: Optional[StrategyCreate] = None
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
    equity_curve: List[Dict[str, Any]] = []
    overfit_risk_score: float
    ai_review: str
    is_simulated: bool = True


# ---------- Paper Trading ----------

class PaperTradeCreate(BaseModel):
    asset: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO
    direction: Literal["long", "short"] = "long"
    quantity: float = Field(..., gt=0)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    notes: Optional[str] = None
    strategy_id: Optional[str] = None


class PaperTradeOut(BaseModel):
    id: str
    user_id: str
    asset: str
    asset_class: AssetClass
    direction: str
    quantity: float
    entry_price: float
    current_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    status: str
    notes: Optional[str] = None
    strategy_id: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    ai_review: Optional[str] = None


# ---------- Risk ----------

class RiskReview(BaseModel):
    score: float = Field(..., ge=0, le=100)
    level: RiskLevel
    main_factors: List[str] = []
    suggested_mitigation: List[str] = []
    trade_blocked: bool = False
    regime_warning: Optional[str] = None


# ---------- Portfolio ----------

class HoldingCreate(BaseModel):
    asset: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO
    quantity: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    notes: Optional[str] = None


class HoldingOut(BaseModel):
    id: str
    user_id: str
    asset: str
    asset_class: AssetClass
    quantity: float
    entry_price: float
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    allocation_pct: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime


# ---------- Watchlist ----------

class WatchlistItemCreate(BaseModel):
    symbol: str = Field(..., min_length=1)
    asset_class: AssetClass = AssetClass.CRYPTO


class WatchlistItemOut(BaseModel):
    id: str
    symbol: str
    asset_class: AssetClass
    price: Optional[float] = None
    change_24h: Optional[float] = None
    change_7d: Optional[float] = None
    volume: Optional[float] = None
    added_at: datetime


# ---------- System ----------

class SystemHealth(BaseModel):
    status: str
    api: str = "ok"
    database: str
    coingecko: str = "unknown"
    ai: str = "template"
    auth: str = "ok"
    last_market_refresh: Optional[datetime] = None
    active_users: int = 0
    saved_strategies: int = 0
    paper_trades: int = 0


class PlanInfo(BaseModel):
    id: str
    name: str
    price_monthly: int
    setup_fee: Optional[int] = None
    features: List[str] = []
    ai_reviews_per_month: int = 0
    max_watchlist: int = 10
    seats: Optional[int] = None
