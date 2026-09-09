"""
Cross-Asset Correlation Engine.

Computes pairwise Pearson correlations across the multi-asset universe
(crypto, stocks, ETFs, forex, commodities, macro). In demo mode the series
are deterministic synthetic walks (labelled source=demo / simulated=True) so
the radar is stable but never masquerades as live measurement. In live mode
the engine uses the real rolling observations accumulated by the market data
service — and if too few exist, the pair is honestly omitted.

Research & simulation only. Not financial advice.
"""

import math
from dataclasses import dataclass

from app.core.config import settings
from app.models.schemas import AssetClass, CorrelationPair
from app.services.market_data import market_data_service

# (asset_a, class_a, asset_b, class_b, relationship_type)
PAIR_UNIVERSE: list[tuple[str, str, str, str, str]] = [
    ("BTC", "crypto", "QQQ", "etf", "Risk asset correlation"),
    ("BTC", "crypto", "DXY", "macro", "Inverse (dollar strength)"),
    ("COIN", "stock", "BTC", "crypto", "Crypto-equity sympathy"),
    ("MSTR", "stock", "BTC", "crypto", "High-beta BTC proxy"),
    ("BTC", "crypto", "XAUUSD", "commodity", "Weak / regime-dependent"),
    ("ETH", "crypto", "BTC", "crypto", "Crypto sector leader"),
    ("SPY", "etf", "QQQ", "etf", "Broad vs tech equities"),
    ("TLT", "etf", "SPY", "etf", "Bonds vs equities (risk pulse)"),
    ("DXY", "macro", "XAUUSD", "commodity", "Inverse (dollar vs gold)"),
    ("EURUSD", "forex", "DXY", "macro", "Inverse (dollar cross)"),
    ("WTI", "commodity", "EEM", "etf", "Commodity / EM demand"),
    ("GBPUSD", "forex", "EURUSD", "forex", "FX cross correlation"),
    ("XAUUSD", "commodity", "XAGUSD", "commodity", "Precious metals co-move"),
    ("VIX", "macro", "SPY", "etf", "Inverse (fear index vs equity)"),
]

_BUCKET_BREAKS = [0.1, 0.3, 0.5, 0.7]
_STATUS_NAMES = [
    "Near-zero",
    "Weak",
    "Moderate",
    "Strong",
    "Very strong",
]


@dataclass
class PairContext:
    label_a: str
    label_b: str
    asset_a: str
    asset_b: str
    relationship_type: str


def _status_for(corr: float) -> tuple[str, str]:
    """Magnitude bucket + sign-aware status label."""
    magnitude = abs(corr)
    idx = 0
    for i, brk in enumerate(_BUCKET_BREAKS):
        if magnitude > brk:
            idx = i + 1
    strength = _STATUS_NAMES[idx]
    if magnitude < 0.3:
        return "Decoupled", strength
    if magnitude > 0.7:
        return "Locked", strength
    return "Moving in tandem" if corr > 0 else "Diverging", strength


def pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation of two equally-sized series (log-returns expected)."""
    if len(x) != len(y) or len(x) < 3:
        return None
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=False))
    vx = sum((xi - mx) ** 2 for xi in x)
    vy = sum((yi - my) ** 2 for yi in y)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy) ** 0.5


def log_returns(series: list[float]) -> list[float]:
    """Continuous log returns; drops the first point and guards non-positive prices."""
    out: list[float] = []
    for prev, cur in zip(series, series[1:], strict=False):
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


class CorrelationEngine:
    def __init__(self) -> None:
        self._pairs = [
            PairContext(
                label_a=a,
                label_b=b,
                asset_a=ac,
                asset_b=bc,
                relationship_type=rel,
            )
            for a, ac, b, bc, rel in PAIR_UNIVERSE
        ]

    async def scan(self, points: int = 60) -> list[CorrelationPair]:
        simulated = settings.MARKET_DATA_MODE == "demo"
        out: list[CorrelationPair] = []
        for ctx in self._pairs:
            corr = await self._correlation_for(ctx, points)
            if corr is None:
                continue
            status, strength = _status_for(corr)
            risk_warning = None
            if abs(corr) > 0.7:
                risk_warning = (
                    "High co-movement — diversification benefit is minimal here."
                )
            elif corr < -0.5:
                risk_warning = "Strong inverse relationship — moves opposite its peer."
            explanation = (
                f"{ctx.label_a} and {ctx.label_b} show {strength.lower()} "
                f"{'positive' if corr >= 0 else 'negative'} correlation "
                f"({corr:+.2f}), relationship: {status.lower()}."
            )
            out.append(CorrelationPair(
                pair=f"{ctx.label_a} / {ctx.label_b}",
                asset_a=ctx.label_a,
                asset_b=ctx.label_b,
                correlation=round(corr, 2),
                relationship_type=ctx.relationship_type,
                status=status,
                ai_explanation=explanation,
                risk_warning=risk_warning,
                source="demo" if simulated else "live",
                is_simulated=simulated,
            ))
        return out

    async def _correlation_for(self, ctx: PairContext, points: int) -> float | None:
        a_cls = AssetClass(ctx.asset_a)
        b_cls = AssetClass(ctx.asset_b)
        a = await market_data_service.get_series(ctx.label_a, a_cls, points)
        b = await market_data_service.get_series(ctx.label_b, b_cls, points)
        if len(a) < 3 or len(b) < 3:
            return None
        n = min(len(a), len(b))
        return pearson(log_returns(a[-n:]), log_returns(b[-n:]))


correlation_engine = CorrelationEngine()
