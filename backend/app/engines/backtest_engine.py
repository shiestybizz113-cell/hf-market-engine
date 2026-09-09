"""
Backtesting Engine (Phase 1 – simulated results)

Clearly labeled as simulated historical analysis.
Architecture ready for real historical bar data later.
"""

import random
import uuid
from typing import Any

from app.core import ai
from app.models.schemas import BacktestRequest, BacktestResult


class BacktestEngine:
    async def run(self, request: BacktestRequest, user_id: str | None = None) -> BacktestResult:
        strategy = request.strategy
        name = strategy.name if strategy else "Unnamed Strategy"

        # Phase 1: generate realistic simulated metrics
        # (Replace later with actual bar replay + rule engine)
        n_trades = random.randint(12, 48)
        win_rate = round(random.uniform(42, 68), 1)
        avg_win = random.uniform(1.5, 4.5)
        avg_loss = random.uniform(-3.2, -1.2)
        total_return = round(random.uniform(-18, 45), 2)
        max_dd = round(random.uniform(4, 28), 2)
        profit_factor = round(random.uniform(0.7, 2.4), 2)
        best = round(random.uniform(4, 18), 2)
        worst = round(random.uniform(-12, -2), 2)
        avg_trade = round((win_rate / 100 * avg_win) + ((100 - win_rate) / 100 * avg_loss), 2)

        # Simple equity curve
        equity = 10000.0
        curve: list[dict[str, Any]] = [{"day": 0, "equity": equity}]
        for i in range(1, 61):
            daily = random.uniform(-1.8, 2.2)
            equity = max(equity * (1 + daily / 100), equity * 0.7)
            curve.append({"day": i, "equity": round(equity, 2)})

        overfit = round(random.uniform(25, 75), 1)
        metrics = {
            "total_return_pct": total_return,
            "win_rate": win_rate,
            "max_drawdown_pct": max_dd,
            "profit_factor": profit_factor,
            "number_of_trades": n_trades,
            "overfit_risk_score": overfit,
        }
        ai_review = await self._ai_review(metrics, user_id)

        return BacktestResult(
            id=str(uuid.uuid4()),
            strategy_name=name,
            total_return_pct=total_return,
            win_rate=win_rate,
            max_drawdown_pct=max_dd,
            profit_factor=profit_factor,
            average_trade_pct=avg_trade,
            number_of_trades=n_trades,
            best_trade_pct=best,
            worst_trade_pct=worst,
            equity_curve=curve,
            overfit_risk_score=overfit,
            ai_review=ai_review,
            is_simulated=True,
        )

    async def _ai_review(self, metrics: dict[str, Any], user_id: str | None = None) -> str:
        return await ai.backtest_review_for(metrics, user_id=user_id)


backtest_engine = BacktestEngine()
