"""
Tests for the IMPACT_MODEL flag.

The shipping checklist requires testing BOTH flag states in CI. These cover
the enum guard, the production refusal of legacy_random, and the behavioral
difference between the three modes at the fill-price level.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


PROD_BASE = dict(
    ENVIRONMENT="production",
    SECRET_KEY="x" * 40,
    MONGODB_URL="mongodb://appuser:pass@mongo:27017",
    CORS_ORIGINS="https://app.example.com",
    ARCHISYNAPSE_SIGNING_KEY="a" * 64,
)


# --------------------------------------------------------------------------
# Enum guard
# --------------------------------------------------------------------------

def test_default_is_the_model_not_random():
    """A fresh install must not fabricate costs."""
    assert Settings().IMPACT_MODEL == "sqrt_law_v1"


@pytest.mark.parametrize("value", ["sqrt_law_v1", "none", "legacy_random"])
def test_permitted_values_accepted_outside_production(value):
    assert Settings(ENVIRONMENT="development", IMPACT_MODEL=value).IMPACT_MODEL == value


@pytest.mark.parametrize("value", ["random", "sqrt_law", "v1", "", "SQRT_LAW_V1"])
def test_unknown_values_rejected(value):
    with pytest.raises((ValidationError, ValueError)):
        Settings(ENVIRONMENT="development", IMPACT_MODEL=value)


# --------------------------------------------------------------------------
# Production fail-closed
# --------------------------------------------------------------------------

def test_legacy_random_refused_in_production():
    """
    The app must refuse to start rather than serve fabricated cost figures
    to production users. Same posture as the CORS wildcard guard.
    """
    with pytest.raises((ValidationError, ValueError)) as exc:
        Settings(**PROD_BASE, IMPACT_MODEL="legacy_random")
    assert "legacy_random" in str(exc.value)


@pytest.mark.parametrize("value", ["sqrt_law_v1", "none"])
def test_honest_modes_permitted_in_production(value):
    """'none' must be available in production — it is the rollback lever."""
    assert Settings(**PROD_BASE, IMPACT_MODEL=value).IMPACT_MODEL == value


def test_legacy_random_permitted_in_development():
    """Rollback for local debugging stays available outside production."""
    s = Settings(ENVIRONMENT="development", IMPACT_MODEL="legacy_random")
    assert s.IMPACT_MODEL == "legacy_random"


# --------------------------------------------------------------------------
# Behavioral difference at the fill level
# --------------------------------------------------------------------------

class _Order:
    """Minimal stand-in for ParentOrderCreate."""

    quantity = 100.0


class _Quote:
    volume_24h = 30_000_000_000.0
    high_24h = 105.0
    low_24h = 95.0


def _slice_impact(monkeypatch, mode, ctx=None):
    from app.core import config as config_mod
    from app.engines import execution_engine as ee

    monkeypatch.setattr(config_mod.settings, "IMPACT_MODEL", mode, raising=False)
    monkeypatch.setattr(ee.settings, "IMPACT_MODEL", mode, raising=False)

    if ctx is None:
        ctx = ee.PaperExecutionEngine._impact_context(_Quote())

    return ee.PaperExecutionEngine._slice_impact_bps(10.0, 100.0, _Order(), ctx)


def test_mode_none_applies_no_impact(monkeypatch):
    assert _slice_impact(monkeypatch, "none") == 0.0


def test_mode_sqrt_law_is_deterministic(monkeypatch):
    """Same order, same market state, same cost. Every time."""
    a = _slice_impact(monkeypatch, "sqrt_law_v1")
    b = _slice_impact(monkeypatch, "sqrt_law_v1")
    assert a == b
    assert a > 0


def test_mode_legacy_random_is_not_deterministic(monkeypatch):
    """Documents the defect being removed: same inputs, different costs."""
    draws = {_slice_impact(monkeypatch, "legacy_random") for _ in range(20)}
    assert len(draws) > 1


def test_missing_market_data_yields_zero_not_invention(monkeypatch):
    """
    With no ADV or volatility the model returns INSUFFICIENT_DATA, and the
    fill path applies no impact rather than guessing one.
    """
    ctx = {"adv": None, "sigma_daily": None}
    assert _slice_impact(monkeypatch, "sqrt_law_v1", ctx) == 0.0


def test_impact_context_extracts_adv_and_sigma():
    from app.engines.execution_engine import PaperExecutionEngine

    ctx = PaperExecutionEngine._impact_context(_Quote())
    assert ctx["adv"] == 30_000_000_000.0
    assert ctx["sigma_daily"] > 0


def test_impact_context_tolerates_missing_quote():
    from app.engines.execution_engine import PaperExecutionEngine

    ctx = PaperExecutionEngine._impact_context(None)
    assert ctx == {"adv": None, "sigma_daily": None}
