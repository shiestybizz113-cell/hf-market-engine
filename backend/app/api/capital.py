"""
Capital Allocation Command Center API — V2 (Evidence Fabric).

One canonical run across the four lanes (BTC treasury, Bitcoin mining, AI/GPU
compute, Energy/storage) on a single normalized economic frame, a scenario
matrix, and a proposal-only optimizer. The AI Capital Council reviews every run.

Evidence V2 contract:
    Every number that enters the engine is an immutable evidence fact.
    Live providers (BTC price, mining network) are OBSERVED_LIVE facts.
    Operator inputs and catalog references are USER_ASSUMPTION facts.
    Each receipt references every fact it consumed. The proof drawer
    reconstructs the full graph from receipt -> facts -> providers -> sources.
    Conflicts and stale data are surfaced, never hidden.

Every run persists an evidence receipt with evidence_ids and per-lane
evidence quality summaries.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.mining import _catalog_item, _live_context
from app.core import ai
from app.core import assets as A
from app.core import evidence as E
from app.core.capital_allocation import (
    RISK_PROFILES,
    SCENARIO_DEFS,
    _rank_lanes,
    propose_allocation,
    run_capital_allocation,
)
from app.core.capital_evidence import apply_evidence_to_result, prepare_capital_evidence
from app.core.capital_integrity import apply_energy_storage_integrity
from app.core.database import get_db
from app.core.evidence_broker import capture_observation, lane_evidence
from app.core.plans import has_feature, require_feature, try_consume_ai_review
from app.models.schemas import (
    CapitalOptimizeRequest,
    CapitalOptimizeResult,
    CapitalRunRequest,
    CapitalRunResult,
    CapitalScenarioRequest,
    CapitalScenarioResult,
    CapitalScenarioRow,
)

router = APIRouter(prefix="/capital", tags=["capital"])
