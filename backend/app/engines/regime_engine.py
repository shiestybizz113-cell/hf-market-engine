"""
Cross-Asset Regime Engine.

Classifies the current macro regime from a handful of cross-asset proxies —
equities (SPY), long bonds (TLT), dollar (DXY), crypto (BTC), volatility
(VIX), and gold (XAUUSD) — and scores how consistent the signal mix is.

Demo mode: quotes are the provider-simulated set, and the regime snapshot is
labelled simulated. Live mode: real quotes, live label.

Research & simulation only. Not financial advice.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.models.schemas import AssetClass, MarketRegime, RegimeFactor
from app.services.market_data import market_data_service

_WATCH: list[tuple[str, AssetClass]] = [
    ("SPY", AssetClass.ETF),
    ("TLT", AssetClass.ETF),
    ("DXY", AssetClass.MACRO),
    ("BTC", AssetClass.CRYPTO),
    ("VIX", AssetClass.MACRO),
    ("XAUUSD", AssetClass.COMMODITY),
]

_REGIMES: dict[str, tuple[str, str]] = {
    # regime_key -> (label, blurb)
    "risk_on": ("Risk-On", "Equities bid, vol low, bonds soft."),
    "risk_off": ("Risk-Off", "Equities weak, vol high, bonds bid."),
    "crypto_bull": ("Crypto-Led", "Crypto leading risk appetite higher."),
    "dollar_strength": (
        "Dollar Strength",
        "US dollar firm; commodities and cross FX typically under pressure.",
    ),
    "gold_bid": (
        "Gold Bid / Defensive",
        "Gold firm with lagging equities — defensive bid present.",
    ),
    "mixed": (
        "Mixed / No Clear Regime",
        "Cross-asset signals conflict; direction is unresolved.",
    ),
}


@dataclass
class _Signal:
    name: str
    detail: str
    direction: int  # +1 risk-on, -1 risk-off


def total_returns(series: list[float]) -> float | None:
    """Simple total return across a series (fractional)."""
    if len(series) < 2 or series[0] <= 0:
        return None
    return series[-1] / series[0] - 1.0


class RegimeEngine:
    def __init__(self) -> None:
        self._watch = _WATCH

    async def snapshot(self, points: int = 60) -> MarketRegime:
        simulated = settings.MARKET_DATA_MODE == "demo"
        series_map: dict[str, list[float]] = {}
        for sym, cls in self._watch:
            series = await market_data_service.get_series(sym, cls, points)
            if len(series) >= 2:
                series_map[sym] = series

        signals = self._build_signals(series_map)
        score, regime_key = self._classify(signals)
        label, _ = _REGIMES[regime_key]
        return MarketRegime(
            regime=regime_key,
            label=label,
            score=round(score, 1),
            factors=[
                RegimeFactor(name=s.name, signal=s.detail, detail=s.detail)
                for s in signals
            ],
            source="demo" if simulated else "live",
            is_simulated=simulated,
            last_updated=datetime.now(UTC),
        )

    def _build_signals(self, series_map: dict[str, list[float]]) -> list[_Signal]:
        out: list[_Signal] = []
        spy = total_returns(series_map.get("SPY", []))
        if spy is not None:
            out.append(_Signal(
                "Equities (SPY)",
                f"SPY total return {spy * 100:+.1f}% over window",
                1 if spy >= 0 else -1,
            ))
        tlt = total_returns(series_map.get("TLT", []))
        if tlt is not None:
            # Bonds rallying is a risk-off tell.
            out.append(_Signal(
                "Long bonds (TLT)",
                f"TLT total return {tlt * 100:+.1f}% over window",
                -1 if tlt >= 0 else 1,
            ))
        dxy = total_returns(series_map.get("DXY", []))
        if dxy is not None:
            out.append(_Signal(
                "Dollar (DXY)",
                f"DXY total return {dxy * 100:+.1f}% over window",
                1 if dxy >= 0 else -1,
            ))
        btc = total_returns(series_map.get("BTC", []))
        if btc is not None:
            # Crypto decouples from the equity/bond axis — its own signal.
            out.append(_Signal(
                "Crypto (BTC)",
                f"BTC total return {btc * 100:+.1f}% over window",
                1 if btc >= 0 else -1,
            ))
        vix = series_map.get("VIX", [])
        if vix:
            level = vix[-1]
            # High VIX is risk-off regardless of direction.
            out.append(_Signal(
                "Volatility (VIX)",
                f"VIX at {level:.1f}",
                -1 if level >= 20 else 1,
            ))
        gold = total_returns(series_map.get("XAUUSD", []))
        if gold is not None:
            out.append(_Signal(
                "Gold (XAUUSD)",
                f"XAUUSD total return {gold * 100:+.1f}% over window",
                1 if gold >= 0 else -1,
            ))
        return out

    def _classify(self, signals: list[_Signal]) -> tuple[float, str]:
        if not signals:
            return 50.0, "mixed"

        spy = next((s for s in signals if s.name.startswith("Equities")), None)
        tlt = next((s for s in signals if s.name.startswith("Long bonds")), None)
        btc = next((s for s in signals if s.name.startswith("Crypto")), None)
        dxy = next((s for s in signals if s.name.startswith("Dollar")), None)
        gold = next((s for s in signals if s.name.startswith("Gold")), None)
        vix = next((s for s in signals if s.name.startswith("Volatility")), None)

        equity_up = spy is not None and spy.direction > 0
        equity_down = spy is not None and spy.direction < 0
        bonds_bid = tlt is not None and tlt.direction < 0
        vix_elevated = vix is not None and vix.direction < 0
        crypto_bull = btc is not None and btc.direction > 0
        dollar_bull = dxy is not None and dxy.direction > 0
        gold_bull = gold is not None and gold.direction > 0

        # Rank-order the risk regimes: cause-specific beats generic.
        if equity_down and (bonds_bid or vix_elevated):
            regime_key = "risk_off"
        elif equity_up and not vix_elevated:
            regime_key = "risk_on"
        elif crypto_bull and not equity_up and dollar_bull:
            # Crypto led while the dollar firmed — crypto-momentum regime.
            regime_key = "crypto_bull"
        elif not equity_up and gold_bull and not vix_elevated:
            regime_key = "gold_bid"
        elif equity_up and dollar_bull:
            regime_key = "dollar_strength"
        else:
            regime_key = "mixed"

        agreement = sum(1 for s in signals if s.direction > 0)
        total = max(len(signals), 1)
        # How one-sided the cross-asset mix is.
        bias = abs(agreement / total - 0.5) * 2  # 0..1

        if regime_key in ("risk_on", "dollar_strength"):
            score = 55 + bias * 30 + (1 if equity_up else 0) * 15
        elif regime_key in ("risk_off", "gold_bid"):
            score = 55 + bias * 30 + (1 if not equity_up else 0) * 15
        elif regime_key == "crypto_bull":
            score = 55 + bias * 30 + (15 if crypto_bull else 0)
        else:
            score = 50 + bias * 20
        return max(0.0, min(100.0, score)), regime_key


regime_engine = RegimeEngine()
