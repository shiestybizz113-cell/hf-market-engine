"""
Market Impact Model — square-root law with linear crossover.

Pure functions. No I/O, no randomness, no global state.
Every output is deterministic given its inputs and is fully reproducible
from the fields emitted in ImpactEstimate.

DOCTRINE
--------
This module never fabricates an estimate. If the inputs required by the
model are missing or non-physical, it returns an estimate with
`evidence_state = INSUFFICIENT_DATA` and `impact_bps = None`. Callers
MUST NOT substitute a default. A missing impact estimate is a fact worth
reporting; an invented one is not.

MODEL
-----
The dominant empirical regularity for metaorder impact is the square-root
law (Bouchaud et al.; confirmed on TSE account-level data and on
reconstructed US large-cap metaorders):

    I(Q) = Y * sigma * sqrt(Q / V)

    Q     : metaorder notional
    V     : average daily volume, same units as Q
    sigma : volatility over the same horizon as V (daily)
    Y     : dimensionless prefactor, order 0.5-1.0
    I     : impact as a fraction of price

Empirically small orders sit closer to a linear regime and cross over into
the square-root regime as participation grows. We implement that crossover
explicitly rather than extrapolating sqrt down to zero, where it badly
overstates cost for tiny orders.

This is a PRE-TRADE ESTIMATE. It is not a realized measurement. Realized
impact must be computed from fills and compared against this estimate; see
`realized_impact_bps`.

LIMITS
------
- Y is UNCALIBRATED at 0.6 (literature midpoint). It has not been fitted
  against this system's own fills. Until it is, every estimate carries
  evidence_state = ESTIMATED_UNCALIBRATED.
- Schedule-independent by construction. The square-root law depends on
  total Q, not on the slicing path, provided participation is not extreme.
  It therefore cannot distinguish TWAP from VWAP from POV. Do not use it
  to rank execution algorithms.
- No transient decay. This returns peak impact, not the residual after
  book replenishment. A propagator kernel would be required for that.
- volume_24h is used as an ADV proxy. For a 24/7 crypto venue that is
  reasonable. For an equity it is a single day, not an average.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

# Model identity. Bump on ANY change to the formula or defaults, because
# receipts signed under a given version must remain reproducible.
MODEL_NAME = "sqrt_law"
MODEL_VERSION = "v1"
MODEL_ID = f"{MODEL_NAME}_{MODEL_VERSION}"

# 1 / (4 * ln 2), the Parkinson estimator constant.
_PARKINSON_K = 1.0 / (4.0 * math.log(2.0))


class ImpactEvidenceState(str, Enum):
    """
    How much trust an impact number has earned.

    INSUFFICIENT_DATA
        Required inputs absent or non-physical. impact_bps is None.
    ESTIMATED_UNCALIBRATED
        Model ran on valid inputs, but the prefactor Y has not been fitted
        against this system's own realized fills. Directionally useful,
        not a cost commitment.
    ESTIMATED_CALIBRATED
        Y was fitted against a documented sample of realized fills.
        Requires calibration_ref to be set.
    MEASURED
        Not a model output at all. Realized impact computed from actual
        fills against a recorded arrival price.
    """

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ESTIMATED_UNCALIBRATED = "ESTIMATED_UNCALIBRATED"
    ESTIMATED_CALIBRATED = "ESTIMATED_CALIBRATED"
    MEASURED = "MEASURED"


class VolatilitySource(str, Enum):
    PARKINSON_24H = "parkinson_24h"  # derived from high_24h / low_24h
    SUPPLIED = "supplied"            # caller passed sigma directly
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ImpactParams:
    """
    Model parameters. Frozen so a receipt cannot be retroactively altered
    by mutating the params object it referenced.

    Y
        Square-root law prefactor. Literature range 0.5-1.0. Default 0.6.
        UNCALIBRATED against this system.
    crossover_participation
        Participation below which impact is treated as linear rather than
        square-root. The two regimes are joined continuously at this point.
    max_participation
        Advisory ceiling. Exceeding it does not raise; it sets
        `exceeds_max_participation` so the caller (or a risk gate) decides.
    half_spread_bps
        Optional fixed spread-crossing cost added to impact to give an
        all-in estimate. Set to 0.0 to report impact alone.
    calibration_ref
        Identifier for the documented fill sample Y was fitted against.
        While None, estimates stay ESTIMATED_UNCALIBRATED.
    """

    Y: float = 0.6
    crossover_participation: float = 0.001
    max_participation: float = 0.03
    half_spread_bps: float = 0.0
    calibration_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if self.Y <= 0:
            raise ValueError("Y must be positive")
        if not 0 < self.crossover_participation < 1:
            raise ValueError("crossover_participation must be in (0, 1)")
        if not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0, 1]")
        if self.half_spread_bps < 0:
            raise ValueError("half_spread_bps must be non-negative")


@dataclass(frozen=True)
class ImpactEstimate:
    """
    Complete, self-describing impact estimate.

    Every field needed to reproduce the number is present, which is what
    makes this signable as a decision receipt: a verifier holding only the
    receipt can recompute impact_bps and confirm it.
    """

    # Verdict
    evidence_state: ImpactEvidenceState
    impact_bps: Optional[float]
    total_cost_bps: Optional[float]      # impact + half_spread
    total_cost_notional: Optional[float]

    # Inputs, echoed for reproducibility
    notional: float
    adv: Optional[float]
    sigma_daily: Optional[float]
    sigma_source: VolatilitySource

    # Derived
    participation: Optional[float]
    regime: Optional[str]                # "linear" | "sqrt"
    exceeds_max_participation: bool

    # Model identity
    model_id: str
    params: dict

    # Why, when INSUFFICIENT_DATA
    reason: Optional[str] = None

    def as_receipt_fields(self) -> dict:
        """
        Flat dict suitable for embedding in an Archisynapse v1.1 receipt
        payload. Enum values are unwrapped to strings so the signed bytes
        are stable across Python versions.
        """
        return {
            "impact_model_id": self.model_id,
            "impact_evidence_state": self.evidence_state.value,
            "impact_bps": self.impact_bps,
            "impact_total_cost_bps": self.total_cost_bps,
            "impact_total_cost_notional": self.total_cost_notional,
            "impact_notional": self.notional,
            "impact_adv": self.adv,
            "impact_sigma_daily": self.sigma_daily,
            "impact_sigma_source": self.sigma_source.value,
            "impact_participation": self.participation,
            "impact_regime": self.regime,
            "impact_exceeds_max_participation": self.exceeds_max_participation,
            "impact_params": self.params,
            "impact_reason": self.reason,
        }


def parkinson_sigma(high: Optional[float], low: Optional[float]) -> Optional[float]:
    """
    Parkinson range-based volatility estimate for a single period.

        sigma = sqrt( (1 / (4 ln 2)) * ln(H/L)^2 )

    Returns volatility over the SAME period as the high/low window, i.e.
    passing high_24h and low_24h yields a daily sigma. Not annualized.

    Range estimators are roughly five times more efficient than
    close-to-close for a single observation, which matters here because we
    have exactly one observation.

    Returns None if inputs are missing or non-physical.
    """
    if high is None or low is None:
        return None
    if high <= 0 or low <= 0 or high < low:
        return None
    if high == low:
        return 0.0
    return math.sqrt(_PARKINSON_K * math.log(high / low) ** 2)


def square_root_impact(
    participation: float,
    sigma_daily: float,
    params: ImpactParams,
) -> tuple[float, str]:
    """
    Core impact kernel. Returns (impact_as_fraction, regime).

    Below params.crossover_participation impact is linear; above it,
    square-root. The regimes are joined continuously: at the crossover
    point both branches return Y * sigma * sqrt(crossover).

    Kept separate from estimate_impact so it can be unit-tested against
    the closed form without constructing quote data.
    """
    if participation < 0:
        raise ValueError("participation must be non-negative")
    if sigma_daily < 0:
        raise ValueError("sigma_daily must be non-negative")

    if participation == 0.0:
        return 0.0, "linear"

    xover = params.crossover_participation
    if participation < xover:
        # Linear branch, scaled to meet sqrt branch at the crossover.
        impact = params.Y * sigma_daily * math.sqrt(xover) * (participation / xover)
        return impact, "linear"

    impact = params.Y * sigma_daily * math.sqrt(participation)
    return impact, "sqrt"


def estimate_impact(
    notional: float,
    adv: Optional[float],
    *,
    sigma_daily: Optional[float] = None,
    high_24h: Optional[float] = None,
    low_24h: Optional[float] = None,
    params: Optional[ImpactParams] = None,
) -> ImpactEstimate:
    """
    Estimate pre-trade market impact for a parent order.

    Parameters
    ----------
    notional
        Absolute order notional. Side does not affect magnitude; apply the
        sign at the fill-price step, not here.
    adv
        Average daily volume in the same currency units as notional. For
        crypto, quote.volume_24h is an acceptable proxy.
    sigma_daily
        Daily volatility as a fraction. If omitted, derived from
        high_24h / low_24h via the Parkinson estimator.
    high_24h, low_24h
        Used only when sigma_daily is not supplied.
    params
        Model parameters. Defaults to ImpactParams().

    Returns
    -------
    ImpactEstimate
        With evidence_state = INSUFFICIENT_DATA and impact_bps = None when
        the model cannot legitimately run. Callers MUST NOT default a
        missing estimate to zero or to any constant.
    """
    params = params or ImpactParams()
    params_dict = asdict(params)

    def insufficient(reason: str, sigma_src: VolatilitySource) -> ImpactEstimate:
        return ImpactEstimate(
            evidence_state=ImpactEvidenceState.INSUFFICIENT_DATA,
            impact_bps=None,
            total_cost_bps=None,
            total_cost_notional=None,
            notional=notional,
            adv=adv,
            sigma_daily=sigma_daily,
            sigma_source=sigma_src,
            participation=None,
            regime=None,
            exceeds_max_participation=False,
            model_id=MODEL_ID,
            params=params_dict,
            reason=reason,
        )

    # --- Validate notional -------------------------------------------------
    if notional is None or notional < 0 or not math.isfinite(notional):
        return insufficient("notional missing or non-physical", VolatilitySource.UNAVAILABLE)

    # --- Resolve sigma -----------------------------------------------------
    if sigma_daily is not None:
        sigma_src = VolatilitySource.SUPPLIED
        sigma = sigma_daily
    else:
        sigma = parkinson_sigma(high_24h, low_24h)
        sigma_src = (
            VolatilitySource.PARKINSON_24H if sigma is not None else VolatilitySource.UNAVAILABLE
        )

    if sigma is None:
        return insufficient(
            "volatility unavailable: sigma_daily not supplied and high/low insufficient",
            sigma_src,
        )
    if not math.isfinite(sigma) or sigma < 0:
        return insufficient("volatility non-physical", sigma_src)

    # --- Validate ADV ------------------------------------------------------
    if adv is None or not math.isfinite(adv) or adv <= 0:
        return insufficient("ADV missing or non-positive", sigma_src)

    # --- Model -------------------------------------------------------------
    participation = notional / adv
    impact_frac, regime = square_root_impact(participation, sigma, params)

    impact_bps = impact_frac * 10_000.0
    total_bps = impact_bps + params.half_spread_bps
    total_notional = notional * total_bps / 10_000.0

    state = (
        ImpactEvidenceState.ESTIMATED_CALIBRATED
        if params.calibration_ref
        else ImpactEvidenceState.ESTIMATED_UNCALIBRATED
    )

    return ImpactEstimate(
        evidence_state=state,
        impact_bps=impact_bps,
        total_cost_bps=total_bps,
        total_cost_notional=total_notional,
        notional=notional,
        adv=adv,
        sigma_daily=sigma,
        sigma_source=sigma_src,
        participation=participation,
        regime=regime,
        exceeds_max_participation=participation > params.max_participation,
        model_id=MODEL_ID,
        params=params_dict,
    )


def max_notional_for_impact_budget(
    max_impact_bps: float,
    adv: float,
    sigma_daily: float,
    params: Optional[ImpactParams] = None,
) -> float:
    """
    Largest notional whose estimated impact stays within a bps budget,
    also respecting params.max_participation.

    Closed form in the square-root regime — no search required. Inverting
    I = Y * sigma * sqrt(Q/V):

        Q = V * (I / (Y * sigma))^2

    Returns 0.0 if sigma is zero (no impact model is meaningful) or if the
    budget is non-positive.
    """
    params = params or ImpactParams()

    if max_impact_bps <= 0 or adv <= 0 or sigma_daily <= 0:
        return 0.0

    target_frac = max_impact_bps / 10_000.0
    xover = params.crossover_participation
    impact_at_xover = params.Y * sigma_daily * math.sqrt(xover)

    if target_frac >= impact_at_xover:
        participation = (target_frac / (params.Y * sigma_daily)) ** 2
    else:
        # Linear branch.
        participation = xover * (target_frac / impact_at_xover)

    participation = min(participation, params.max_participation)
    return participation * adv


def realized_impact_bps(
    arrival_price: float,
    avg_fill_price: float,
    side: str,
) -> Optional[float]:
    """
    MEASURED implementation shortfall in bps, signed so that positive means
    the fill was worse than arrival.

    This is a measurement, not a model output. Compare it against the
    corresponding ImpactEstimate to calibrate Y — that comparison is the
    only legitimate path from ESTIMATED_UNCALIBRATED to
    ESTIMATED_CALIBRATED.

    Returns None on non-physical input.
    """
    if arrival_price is None or avg_fill_price is None:
        return None
    if arrival_price <= 0 or avg_fill_price <= 0:
        return None
    side_norm = side.lower().strip()
    if side_norm not in ("buy", "sell"):
        return None

    direction = 1.0 if side_norm == "buy" else -1.0
    return direction * (avg_fill_price - arrival_price) / arrival_price * 10_000.0
