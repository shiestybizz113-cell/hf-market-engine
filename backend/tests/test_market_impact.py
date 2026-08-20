"""
Tests for app.services.market_impact.

Covers the closed form, regime continuity, the refuse-to-fabricate
contract, budget inversion, and realized-impact sign convention.
"""

import math

import pytest

from app.services.market_impact import (
    MODEL_ID,
    ImpactEvidenceState,
    ImpactParams,
    VolatilitySource,
    estimate_impact,
    max_notional_for_impact_budget,
    parkinson_sigma,
    realized_impact_bps,
    square_root_impact,
)


# --------------------------------------------------------------------------
# Closed form
# --------------------------------------------------------------------------

def test_sqrt_law_matches_closed_form():
    """I = Y * sigma * sqrt(Q/V), computed independently."""
    params = ImpactParams(Y=0.6)
    notional, adv, sigma = 1_000_000.0, 100_000_000.0, 0.04

    est = estimate_impact(notional, adv, sigma_daily=sigma, params=params)

    expected_bps = 0.6 * 0.04 * math.sqrt(notional / adv) * 10_000
    assert est.impact_bps == pytest.approx(expected_bps)
    assert est.regime == "sqrt"


def test_impact_scales_as_sqrt_not_linear():
    """Quadrupling size roughly doubles impact — the whole point of SRL."""
    params = ImpactParams()
    kw = dict(adv=100_000_000.0, sigma_daily=0.04, params=params)

    small = estimate_impact(1_000_000.0, **kw)
    big = estimate_impact(4_000_000.0, **kw)

    assert big.impact_bps == pytest.approx(2.0 * small.impact_bps)


def test_impact_monotonic_in_size():
    params = ImpactParams()
    prev = -1.0
    for notional in (1e4, 1e5, 1e6, 1e7):
        est = estimate_impact(notional, 1e8, sigma_daily=0.04, params=params)
        assert est.impact_bps > prev
        prev = est.impact_bps


# --------------------------------------------------------------------------
# Regime crossover
# --------------------------------------------------------------------------

def test_regimes_join_continuously_at_crossover():
    """No discontinuity in cost as an order crosses the regime boundary."""
    params = ImpactParams(crossover_participation=0.001)
    sigma = 0.04

    eps = 1e-9
    below, regime_below = square_root_impact(0.001 - eps, sigma, params)
    at, regime_at = square_root_impact(0.001, sigma, params)

    assert regime_below == "linear"
    assert regime_at == "sqrt"
    assert below == pytest.approx(at, rel=1e-6)


def test_small_orders_use_linear_regime():
    params = ImpactParams(crossover_participation=0.001)
    est = estimate_impact(1_000.0, 100_000_000.0, sigma_daily=0.04, params=params)
    assert est.regime == "linear"
    assert est.participation < params.crossover_participation


def test_zero_notional_has_zero_impact():
    est = estimate_impact(0.0, 1e8, sigma_daily=0.04)
    assert est.impact_bps == pytest.approx(0.0)


def test_zero_volatility_has_zero_impact():
    """A perfectly still market implies no impact under this model."""
    est = estimate_impact(1e6, 1e8, sigma_daily=0.0)
    assert est.impact_bps == pytest.approx(0.0)
    assert est.evidence_state is ImpactEvidenceState.ESTIMATED_UNCALIBRATED


# --------------------------------------------------------------------------
# Refuse to fabricate
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "adv",
    [None, 0.0, -1.0, float("nan"), float("inf")],
)
def test_bad_adv_returns_insufficient_not_a_number(adv):
    est = estimate_impact(1e6, adv, sigma_daily=0.04)
    assert est.evidence_state is ImpactEvidenceState.INSUFFICIENT_DATA
    assert est.impact_bps is None
    assert est.total_cost_bps is None
    assert est.reason


def test_missing_volatility_returns_insufficient():
    """No sigma and no usable high/low: refuse, do not default."""
    est = estimate_impact(1e6, 1e8)
    assert est.evidence_state is ImpactEvidenceState.INSUFFICIENT_DATA
    assert est.impact_bps is None
    assert est.sigma_source is VolatilitySource.UNAVAILABLE


def test_negative_notional_returns_insufficient():
    est = estimate_impact(-1e6, 1e8, sigma_daily=0.04)
    assert est.evidence_state is ImpactEvidenceState.INSUFFICIENT_DATA


# --------------------------------------------------------------------------
# Volatility estimation
# --------------------------------------------------------------------------

def test_parkinson_matches_closed_form():
    high, low = 105.0, 95.0
    expected = math.sqrt((1 / (4 * math.log(2))) * math.log(high / low) ** 2)
    assert parkinson_sigma(high, low) == pytest.approx(expected)


def test_parkinson_zero_range_is_zero_vol():
    assert parkinson_sigma(100.0, 100.0) == 0.0


@pytest.mark.parametrize(
    "high,low",
    [(None, 95.0), (105.0, None), (95.0, 105.0), (0.0, 0.0), (-1.0, -2.0)],
)
def test_parkinson_rejects_bad_input(high, low):
    assert parkinson_sigma(high, low) is None


def test_sigma_derived_from_high_low_when_not_supplied():
    est = estimate_impact(1e6, 1e8, high_24h=105.0, low_24h=95.0)
    assert est.sigma_source is VolatilitySource.PARKINSON_24H
    assert est.sigma_daily == pytest.approx(parkinson_sigma(105.0, 95.0))
    assert est.impact_bps is not None


def test_supplied_sigma_takes_precedence_over_high_low():
    est = estimate_impact(1e6, 1e8, sigma_daily=0.10, high_24h=105.0, low_24h=95.0)
    assert est.sigma_source is VolatilitySource.SUPPLIED
    assert est.sigma_daily == pytest.approx(0.10)


# --------------------------------------------------------------------------
# Participation ceiling
# --------------------------------------------------------------------------

def test_exceeding_max_participation_flags_but_does_not_raise():
    """Advisory, not enforcement. The risk gate decides, not the model."""
    params = ImpactParams(max_participation=0.03)
    est = estimate_impact(10_000_000.0, 100_000_000.0, sigma_daily=0.04, params=params)

    assert est.participation == pytest.approx(0.10)
    assert est.exceeds_max_participation is True
    assert est.impact_bps is not None  # still reports a number


def test_within_max_participation_not_flagged():
    params = ImpactParams(max_participation=0.03)
    est = estimate_impact(1_000_000.0, 100_000_000.0, sigma_daily=0.04, params=params)
    assert est.exceeds_max_participation is False


# --------------------------------------------------------------------------
# Budget inversion
# --------------------------------------------------------------------------

def test_budget_inversion_round_trips():
    """Sizing to a budget then estimating should land back on the budget."""
    params = ImpactParams(Y=0.6, max_participation=1.0)
    adv, sigma, budget_bps = 100_000_000.0, 0.04, 15.0

    notional = max_notional_for_impact_budget(budget_bps, adv, sigma, params)
    est = estimate_impact(notional, adv, sigma_daily=sigma, params=params)

    assert est.impact_bps == pytest.approx(budget_bps, rel=1e-6)


def test_budget_inversion_respects_max_participation():
    params = ImpactParams(Y=0.6, max_participation=0.02)
    adv = 100_000_000.0

    # A budget generous enough that participation would otherwise blow past 2%.
    notional = max_notional_for_impact_budget(500.0, adv, 0.04, params)
    assert notional == pytest.approx(0.02 * adv)


@pytest.mark.parametrize(
    "budget,adv,sigma",
    [(0.0, 1e8, 0.04), (-5.0, 1e8, 0.04), (15.0, 0.0, 0.04), (15.0, 1e8, 0.0)],
)
def test_budget_inversion_degenerate_inputs_return_zero(budget, adv, sigma):
    assert max_notional_for_impact_budget(budget, adv, sigma) == 0.0


# --------------------------------------------------------------------------
# Realized impact
# --------------------------------------------------------------------------

def test_realized_impact_buy_worse_than_arrival_is_positive():
    assert realized_impact_bps(100.0, 100.10, "buy") == pytest.approx(10.0)


def test_realized_impact_sell_worse_than_arrival_is_positive():
    """Selling below arrival is also a cost, so the sign must flip."""
    assert realized_impact_bps(100.0, 99.90, "sell") == pytest.approx(10.0)


def test_realized_impact_favourable_fill_is_negative():
    assert realized_impact_bps(100.0, 99.90, "buy") == pytest.approx(-10.0)


@pytest.mark.parametrize(
    "arrival,fill,side",
    [(0.0, 100.0, "buy"), (100.0, 0.0, "buy"), (None, 100.0, "buy"), (100.0, 100.0, "hodl")],
)
def test_realized_impact_rejects_bad_input(arrival, fill, side):
    assert realized_impact_bps(arrival, fill, side) is None


# --------------------------------------------------------------------------
# Receipt contract
# --------------------------------------------------------------------------

def test_receipt_fields_are_json_safe_and_complete():
    """Signed bytes must be stable: no enum objects, no dataclass instances."""
    import json

    est = estimate_impact(1e6, 1e8, sigma_daily=0.04)
    fields = est.as_receipt_fields()

    json.dumps(fields)  # raises if anything is unserializable

    assert fields["impact_model_id"] == MODEL_ID
    assert fields["impact_evidence_state"] == "ESTIMATED_UNCALIBRATED"
    assert isinstance(fields["impact_params"], dict)
    assert fields["impact_params"]["Y"] == 0.6


def test_receipt_is_reproducible_from_its_own_fields():
    """
    A verifier holding only the receipt can recompute the impact number.
    This is what makes the receipt meaningful rather than decorative.
    """
    est = estimate_impact(2_500_000.0, 7.5e8, sigma_daily=0.037)
    f = est.as_receipt_fields()

    recomputed = estimate_impact(
        f["impact_notional"],
        f["impact_adv"],
        sigma_daily=f["impact_sigma_daily"],
        params=ImpactParams(**f["impact_params"]),
    )
    assert recomputed.impact_bps == pytest.approx(f["impact_bps"])


def test_uncalibrated_by_default_calibrated_only_with_ref():
    plain = estimate_impact(1e6, 1e8, sigma_daily=0.04)
    assert plain.evidence_state is ImpactEvidenceState.ESTIMATED_UNCALIBRATED

    calibrated = estimate_impact(
        1e6, 1e8, sigma_daily=0.04,
        params=ImpactParams(calibration_ref="fills_2026Q3_n=1482"),
    )
    assert calibrated.evidence_state is ImpactEvidenceState.ESTIMATED_CALIBRATED


def test_params_are_immutable():
    """A signed receipt must not be alterable by mutating shared params."""
    import dataclasses

    params = ImpactParams()
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.Y = 99.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# Guard rails
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"Y": 0.0},
        {"Y": -1.0},
        {"crossover_participation": 0.0},
        {"crossover_participation": 1.0},
        {"max_participation": 0.0},
        {"max_participation": 1.5},
        {"half_spread_bps": -1.0},
    ],
)
def test_invalid_params_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        ImpactParams(**kwargs)


def test_half_spread_added_to_total_but_not_to_impact():
    params = ImpactParams(half_spread_bps=2.5)
    est = estimate_impact(1e6, 1e8, sigma_daily=0.04, params=params)
    assert est.total_cost_bps == pytest.approx(est.impact_bps + 2.5)


def test_model_is_deterministic():
    """No randomness. Same inputs, same bytes, every time."""
    a = estimate_impact(1e6, 1e8, sigma_daily=0.04).as_receipt_fields()
    b = estimate_impact(1e6, 1e8, sigma_daily=0.04).as_receipt_fields()
    assert a == b
