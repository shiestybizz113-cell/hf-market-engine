"""
Risk Engine

Every signal, strategy and paper trade should pass through risk checks.
"""

from typing import List, Optional
from app.models.schemas import (
    RiskReview, RiskLevel, TradeIdea, PaperTradeCreate, StrategyCreate
)


class RiskEngine:
    def score_trade_idea(self, idea: TradeIdea) -> RiskReview:
        factors = []
        score = idea.risk_score  # start from provided

        if idea.confidence < 60:
            factors.append("Low confidence signal")
            score += 5
        if idea.risk_score > 75:
            factors.append("Elevated inherent risk score")
        if idea.signal_type.value in ("risk_off_warning", "liquidity_warning"):
            factors.append("Defensive / liquidity warning signal type")
            score += 10
        if idea.asset_class.value in ("crypto", "stock") and idea.direction.value == "bullish":
            factors.append("Directional exposure in risk asset")

        score = min(100, max(0, score))
        level = self._level(score)
        blocked = level == RiskLevel.EXTREME

        mitigation = []
        if score > 70:
            mitigation.append("Reduce position size")
            mitigation.append("Tighten invalidation / stop")
        if blocked:
            mitigation.append("Trade blocked under current risk rules")
        if not mitigation:
            mitigation.append("Standard risk parameters acceptable")

        return RiskReview(
            score=round(score, 1),
            level=level,
            main_factors=factors or ["Standard risk profile"],
            suggested_mitigation=mitigation,
            trade_blocked=blocked,
            regime_warning=idea.macro_context,
        )

    def score_paper_trade(self, trade: PaperTradeCreate, portfolio_value: float = 10000.0) -> RiskReview:
        factors = []
        score = 40.0

        notional = (trade.quantity * (trade.entry_price or 100))
        position_pct = (notional / portfolio_value) * 100 if portfolio_value > 0 else 100

        if position_pct > 10:
            factors.append(f"Position size {position_pct:.1f}% exceeds recommended max")
            score += 25
        elif position_pct > 5:
            factors.append(f"Position size {position_pct:.1f}% is elevated")
            score += 12

        if trade.stop_loss is None:
            factors.append("No stop-loss defined")
            score += 15
        if trade.take_profit is None:
            factors.append("No take-profit defined")
            score += 5

        if trade.asset_class.value == "crypto":
            factors.append("Crypto volatility premium")
            score += 8

        score = min(100, max(0, score))
        level = self._level(score)
        blocked = level == RiskLevel.EXTREME or position_pct > 20

        mitigation = []
        if position_pct > 5:
            mitigation.append("Consider reducing size to ≤5% of portfolio")
        if trade.stop_loss is None:
            mitigation.append("Define a stop-loss before entry")
        if blocked:
            mitigation.append("Trade blocked — risk limits exceeded")

        return RiskReview(
            score=round(score, 1),
            level=level,
            main_factors=factors or ["Within standard parameters"],
            suggested_mitigation=mitigation or ["Proceed with defined risk"],
            trade_blocked=blocked,
        )

    def score_strategy(self, strategy: StrategyCreate) -> RiskReview:
        factors = []
        score = 35.0

        if strategy.stop_loss_pct > 5:
            factors.append("Wide stop-loss increases risk per trade")
            score += 15
        if strategy.max_position_pct > 10:
            factors.append("Max position size above 10%")
            score += 20
        if strategy.max_daily_loss_pct > 5:
            factors.append("Daily loss limit is elevated")
            score += 10
        if not strategy.market_regime_filter:
            factors.append("No market regime filter applied")
            score += 8

        score = min(100, max(0, score))
        level = self._level(score)

        mitigation = []
        if strategy.max_position_pct > 5:
            mitigation.append("Consider capping max position at 5%")
        if strategy.stop_loss_pct > 3:
            mitigation.append("Tighten stop-loss if volatility allows")
        if not mitigation:
            mitigation.append("Strategy risk parameters look reasonable")

        return RiskReview(
            score=round(score, 1),
            level=level,
            main_factors=factors or ["Balanced risk parameters"],
            suggested_mitigation=mitigation,
            trade_blocked=level == RiskLevel.EXTREME,
        )

    def _level(self, score: float) -> RiskLevel:
        if score >= 85:
            return RiskLevel.EXTREME
        if score >= 70:
            return RiskLevel.HIGH
        if score >= 45:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


risk_engine = RiskEngine()
