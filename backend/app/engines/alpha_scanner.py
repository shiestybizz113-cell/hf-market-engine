"""
Cross-Asset Alpha Scanner.

Ranks every symbol across the multi-asset universe by a momentum composite
(24h / 7d / 30d change blend) using the current quote set. Demo mode returns
ranked demo quotes — explicitly NO anomaly detection in demo (that arrives
with a live-data phase). Output is research-grade ranking only.

Research & simulation only. Not financial advice.
"""

from datetime import UTC, datetime

from app.core.config import settings
from app.models.schemas import (
    AlphaScanItem,
    AlphaScanResult,
    AssetClass,
)
from app.services.market_data import market_data_service

_SCAN_CLASSES = [
    AssetClass.CRYPTO,
    AssetClass.STOCK,
    AssetClass.ETF,
    AssetClass.FOREX,
    AssetClass.COMMODITY,
]


class AlphaScanner:
    async def scan(self, limit: int = 20) -> AlphaScanResult:
        simulated = settings.MARKET_DATA_MODE == "demo"
        items: list[AlphaScanItem] = []
        for cls in _SCAN_CLASSES:
            quotes = await market_data_service.class_quotes(cls)
            for sym, q in quotes.items():
                score, drivers = self._momentum(q)
                items.append(AlphaScanItem(
                    symbol=sym,
                    name=sym,
                    asset_class=cls,
                    price=q.price,
                    change_24h=q.change_24h,
                    momentum_score=score,
                    rationale="; ".join(drivers),
                    source="demo" if simulated else "live",
                ))
        items.sort(key=lambda it: it.momentum_score, reverse=True)
        return AlphaScanResult(
            generated_at=datetime.now(UTC),
            is_simulated=simulated,
            anomaly_detection="disabled (demo)" if simulated else "enabled",
            items=items[:limit],
            disclaimer=(
                "Demo mode: rankings reflect real-time demo quotes only; "
                "no anomaly detection is performed. Research only, not "
                "financial advice."
                if simulated
                else "Research only, not financial advice."
            ),
        )

    def _momentum(self, q) -> tuple[float, list[str]]:
        """Composite momentum 0-100 + driver notes from one PriceQuote."""
        changes = [
            (q.change_24h, 0.5, "24h"),
            (q.change_7d, 0.3, "7d"),
            (q.change_30d, 0.2, "30d"),
        ]
        raw = 0.0
        drivers: list[str] = []
        for change, weight, label in changes:
            if change is None:
                continue
            # Soft-clip so a single mad spike can't dominate the scaffold.
            clipped = max(-40.0, min(40.0, float(change)))
            raw += clipped / 80.0 * weight  # +/-40% → [-0.5, +0.5] per leg
            drivers.append(f"{label} {clipped:+.1f}%")
        score = 50.0 + raw * 100.0  # weighted total in [-0.5, 0.5] → [0, 100]
        return round(max(0.0, min(100.0, score)), 1), drivers


alpha_scanner = AlphaScanner()
