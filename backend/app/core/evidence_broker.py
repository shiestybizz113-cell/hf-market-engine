"""
Evidence Broker — the single front door between providers/operator inputs and
our immutable evidence fabric.

Responsibilities:
1. capture observations without rewriting history;
2. resolve current facts while surfacing stale/conflicting candidates;
3. roll resolutions into per-lane evidence blocks for Capital receipts/UI.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core import evidence as E

MATERIAL_CHANGE_PCT = 0.5


async def capture_observation(
    *,
    domain: str,
    metric: str,
    subject_id: str,
    value: float,
    unit: str,
    state: str,
    provider: str,
    source_type: str,
    source_reference: Optional[str] = None,
    observed_at: Optional[datetime] = None,
    region: Optional[str] = None,
    confidence: Optional[float] = None,
    methodology: Optional[str] = None,
    user_id: Optional[str] = None,
    raw_snapshot_ref: Optional[str] = None,
    extra: Optional[Dict] = None,
    _db=None,
) -> str:
    """Persist an observation, reusing an equivalent fresh fact when possible.

    Value *and structured metadata* must match for reuse. This matters for fleet
    assets where the unit count can stay constant while power, location, or
    other economically material fields change.
    """
    if state not in E.EVIDENCE_STATES:
        raise ValueError(f"Invalid evidence state: {state}")

    extra = extra or {}
    history = await E.facts_for(
        domain=domain,
        metric=metric,
        subject_id=subject_id,
        user_id=user_id,
        include_stale=True,
        limit=100,
        _db=_db,
    )
    same_source = [
        f for f in history
        if f.get("provider") == provider
        and f.get("source_type") == source_type
        and f.get("region") == region
    ]

    latest = same_source[0] if same_source else None
    for fact in same_source:
        if E.is_stale(fact):
            continue
        old_val = float(fact.get("value", 0.0))
        if abs(old_val) > 1e-12:
            drift = abs(old_val - float(value)) / abs(old_val) * 100.0
        else:
            drift = abs(old_val - float(value))
        metadata_matches = (fact.get("extra") or {}) == extra
        if drift < MATERIAL_CHANGE_PCT and metadata_matches:
            return fact["evidence_id"]

    return await E.ingest_fact(
        domain=domain,
        metric=metric,
        subject_id=subject_id,
        value=float(value),
        unit=unit,
        state=state,
        provider=provider,
        source_type=source_type,
        source_reference=source_reference,
        observed_at=observed_at,
        region=region,
        confidence=confidence,
        methodology=methodology,
        user_id=user_id,
        raw_snapshot_ref=raw_snapshot_ref,
        supersedes=latest.get("evidence_id") if latest else None,
        extra=extra,
        _db=_db,
    )


async def resolve_metric(
    *,
    domain: str,
    metric: str,
    subject_id: str,
    user_id: Optional[str],
    explicit_value: Optional[float] = None,
    explicit_unit: Optional[str] = None,
    explicit_provider: str = "user_input",
    explicit_source_type: str = "user_input",
    explicit_methodology: Optional[str] = None,
    explicit_extra: Optional[Dict] = None,
    _db=None,
) -> Dict:
    """Resolve a metric to its best current fact and preserve the full trace.

    Fresh facts are preferred as a class. Only when no fresh fact exists do we
    resolve from stale history, which allows the caller to surface STALE rather
    than silently returning UNAVAILABLE.
    """
    if explicit_value is not None:
        await capture_observation(
            domain=domain,
            metric=metric,
            subject_id=subject_id,
            value=float(explicit_value),
            unit=explicit_unit or "usd",
            state=E.USER_ASSUMPTION,
            provider=explicit_provider,
            source_type=explicit_source_type,
            methodology=explicit_methodology,
            user_id=user_id,
            extra=explicit_extra or {},
            _db=_db,
        )

    all_facts = await E.facts_for(
        domain=domain,
        metric=metric,
        subject_id=subject_id,
        user_id=user_id,
        include_stale=True,
        limit=100,
        _db=_db,
    )
    fresh = [f for f in all_facts if not E.is_stale(f)]
    candidates = fresh if fresh else all_facts
    summary = E.summarize_resolution(
        candidates,
        explicit_user_input=explicit_value is not None,
    )
    summary["all_candidate_count"] = len(all_facts)
    summary["stale_candidate_count"] = sum(1 for f in all_facts if E.is_stale(f))
    return summary


async def lane_evidence(
    *,
    lane_key: str,
    label: str,
    resolutions: Dict[str, Dict],
) -> Dict:
    """Roll metric resolutions into a lane evidence block.

    Quality is deliberately conservative. Any user assumption/simulation makes
    a lane PARTIAL unless a stronger condition (STALE/CONFLICTING/UNAVAILABLE)
    applies. This prevents a live BTC quote from making an assumption-heavy GPU
    or energy model look fully observed.
    """
    facts_used: List[str] = []
    assumptions_used: List[str] = []
    facts_missing: List[str] = []
    facts_stale: List[str] = []
    metrics: Dict[str, Dict] = {}

    state_counts = {
        E.OBSERVED_LIVE: 0,
        E.USER_ASSUMPTION: 0,
        E.SIMULATION: 0,
        E.UNAVAILABLE: 0,
    }

    for metric_name, res in resolutions.items():
        fact_id = res.get("fact_id")
        state = res.get("state", E.UNAVAILABLE)
        state_counts[state] = state_counts.get(state, 0) + 1
        if fact_id:
            facts_used.append(fact_id)
            if state in (E.USER_ASSUMPTION, E.SIMULATION):
                assumptions_used.append(fact_id)
        if res.get("quality_label") == E.Q_STALE:
            facts_stale.append(metric_name)
        if state == E.UNAVAILABLE or not fact_id:
            facts_missing.append(metric_name)

        metrics[metric_name] = {
            "value": res.get("value"),
            "fact_id": fact_id,
            "state": state,
            "provider": res.get("provider"),
            "source_type": res.get("source_type"),
            "source_reference": res.get("source_reference"),
            "observed_at": res.get("observed_at"),
            "age_seconds": res.get("age_seconds"),
            "fresh": res.get("fresh", False),
            "quality_label": res.get("quality_label", E.Q_UNAVAILABLE),
            "quality_score": res.get("quality_score", 0),
            "explicit_user_input": res.get("explicit_user_input", False),
            "conflicts": res.get("conflicts", []),
            "candidate_count": len(res.get("candidates", [])),
            "stale_candidate_count": res.get("stale_candidate_count", 0),
        }

    used = list(metrics.values())
    labels = {m["quality_label"] for m in used}
    total_conflicts = sum(len(m.get("conflicts", [])) for m in used)
    scores = [m.get("quality_score", 0) for m in used] or [0]

    if not used or E.Q_UNAVAILABLE in labels or facts_missing:
        quality_label = E.Q_UNAVAILABLE
    elif E.Q_STALE in labels or facts_stale:
        quality_label = E.Q_STALE
    elif E.Q_CONFLICTING in labels or total_conflicts:
        quality_label = E.Q_CONFLICTING
    elif state_counts.get(E.USER_ASSUMPTION, 0) or state_counts.get(E.SIMULATION, 0):
        quality_label = E.Q_PARTIAL
    else:
        quality_label = E.Q_COMPLETE

    quality_score = min(scores)
    if quality_label == E.Q_PARTIAL:
        quality_score = min(quality_score, 70)
    elif quality_label == E.Q_CONFLICTING:
        quality_score = min(quality_score, 60)
    elif quality_label == E.Q_STALE:
        quality_score = min(quality_score, 35)
    elif quality_label == E.Q_UNAVAILABLE:
        quality_score = 0

    measured = sum(state_counts.values())
    observed_pct = (
        round(state_counts.get(E.OBSERVED_LIVE, 0) / measured * 100.0, 1)
        if measured else 0.0
    )
    assumption_pct = (
        round(
            (state_counts.get(E.USER_ASSUMPTION, 0) + state_counts.get(E.SIMULATION, 0))
            / measured * 100.0,
            1,
        )
        if measured else 0.0
    )

    return {
        "lane_key": lane_key,
        "label": label,
        "facts_used": list(dict.fromkeys(facts_used)),
        "assumptions_used": list(dict.fromkeys(assumptions_used)),
        "facts_missing": facts_missing,
        "facts_stale": facts_stale,
        "metrics": metrics,
        "quality_label": quality_label,
        "quality_score": quality_score,
        "conflict_count": total_conflicts,
        "state_counts": state_counts,
        "observed_pct": observed_pct,
        "assumption_pct": assumption_pct,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
