"""
Backtesting Engine (Phase 1 – simulated results)

Clearly labeled as simulated historical analysis.
Architecture ready for real historical bar data later.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any
from app.models.schemas import BacktestRequest, BacktestResult, StrategyCreate
import random
import uuid


class BacktestEngine:
    async def run(self, request: BacktestRequest) -> BacktestResult:
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
        curve: List[Dict[str, Any]] = [{"day": 0, "equity": equity}]
        for i in range(1, 61):
            daily = random.uniform(-1.8, 2.2)
            equity = max(equity * (1 + daily / 100), equity * 0.7)
            curve.append({"day": i, "equity": round(equity, 2)})

        overfit = round(random.uniform(25, 75), 1)
        ai_review = self._ai_review(total_return, win_rate, max_dd, profit_factor, n_trades, overfit)

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

    def _ai_review(self, ret, wr, dd, pf, trades, overfit) -> str:
        comments = []
        if ret > 20 and wr > 55 and dd < 15:
            comments.append("Results look promising on the simulated sample.")
        if dd > 20:
            comments.append("Drawdown is elevated — consider tighter risk controls.")
        if pf < 1.1:
            comments.append("Profit factor is marginal; edge may be weak.")
        if trades < 20:
            comments.append("Limited number of trades — statistical significance is low.")
        if overfit > 60:
            comments.append("Overfit risk appears elevated. Strategy may be fragile out of sample.")
        if not comments:
            comments.append("Mixed results. Further testing across regimes is recommended.")

        verdict = "promising but needs more testing"
        if overfit > 70 or dd > 25:
            verdict = "fragile / elevated risk"
        elif ret > 25 and wr > 58 and dd < 12 and overfit < 45:
            verdict = "appears relatively robust on this sample"

        return (
            f"AI Strategy Review (simulated): The strategy appears **{verdict}**. "
            + " ".join(comments)
            + " This is historical simulation only and does not guarantee future performance."
        )


backtest_engine = BacktestEngine()
