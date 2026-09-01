"""
Evidence Broker — the single front door between the live providers / operator
inputs and the immutable evidence fabric.

Three jobs:

1. CAPTURE      persist a fresh observation as an immutable fact. Facts are
                deduped against the latest eligible fact for the same
                (domain, metric, subject, provider): if the new value is not
                materially different AND the old fact is still fresh, we reuse
                the old fact's evidence_id instead of growing the collection.
                Material change or expiry -> a NEW fact is appended and the old
                one is pointed at by ``supersedes``. Nothing is ever edited.

2. RESOLVE      pick the best eligible fact for a metric (evidence state ->
                freshness -> source quality -> explicit user input), and
                produce the public quality summary. Losing candidates and
                conflicts are preserved in the trace, never deleted.

3. SUMMARIZE    roll per-lane metric resolutions into the lane evidence block
                a capital receipt stores (facts_used + quality) so the proof
                drawer can reconstruct exactly which facts each lane consumed.
"""

from datetime import UTC, datetime

from app.core import evidence as E

MATERIAL_CHANGE_PCT = 0.5  # ignore sub-0.5% drift while a fact is fresh


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
    source_reference: str | None = None,
    region: str | None = None,
    confidence: float | None = None,
    methodology: str | None = None,
    user_id: str | None = None,
    raw_snapshot_ref: str | None = None,
    _db=None,
) -> str:
    """Persist a fresh fact (deduped against the latest fresh one).

    Returns the evidence_id that is current for this observation — either a
    reused fresh fact or a newly appended one. The old fact's history is
    preserved either way.
    """
    fresh = await E.eligible_facts(
        domain=domain, metric=metric, subject_id=subject_id,
        user_id=user_id, _db=_db,
    )
    candidates = [f for f in fresh if f.get("provider") == provider]
    for f in candidates:
        old_val = float(f["value"])
        if old_val > 0:
            drift = abs(old_val - value) / old_val * 100.0
        else:
            drift = abs(old_val - value)
        if drift < MATERIAL_CHANGE_PCT:
            return f["evidence_id"]

    supersedes = candidates[0]["evidence_id"] if candidates else None
    return await E.ingest_fact(
        domain=domain, metric=metric, subject_id=subject_id,
        value=value, unit=unit, state=state, provider=provider,
        source_type=source_type, source_reference=source_reference,
        region=region, confidence=confidence, methodology=methodology,
        user_id=user_id, raw_snapshot_ref=raw_snapshot_ref,
        supersedes=supersedes, _db=_db,
    )


async def resolve_metric(
    *,
    domain: str,
    metric: str,
    subject_id: str,
    user_id: str | None,
    explicit_value: float | None = None,
    explicit_unit: str | None = None,
    explicit_provider: str = "user_input",
    explicit_source_type: str = "user_input",
    _db=None,
) -> dict:
    """Resolve a metric to its best fact, persisting an explicit operator
    override as a user_assumption fact when supplied.

    Returns the evidence.summarize_resolution() shape plus ``fact_id``.
    """
    if explicit_value is not None:
        await capture_observation(
            domain=domain, metric=metric, subject_id=subject_id,
            value=explicit_value,
            unit=explicit_unit or "usd",
            state=E.USER_ASSUMPTION,
            provider=explicit_provider,
            source_type=explicit_source_type,
            user_id=user_id,
            _db=_db,
        )
    facts = await E.eligible_facts(
        domain=domain, metric=metric, subject_id=subject_id,
        user_id=user_id, _db=_db,
    )
    summary = E.summarize_resolution(facts, explicit_user_input=explicit_value is not None)
    return summary


async def lane_evidence(
    *,
    lane_key: str,
    label: str,
    resolutions: dict[str, dict],
) -> dict:
    """Roll metric resolutions into a lane evidence block for the receipt.

    Lane quality is the weakest link across the lane's metrics: if any
    consumed metric is STALE / CONFLICTING / UNAVAILABLE the whole lane says
    so, because the lane's numbers depend on it.
    """
    facts_used: list[str] = []
    metrics: dict[str, dict] = {}
    for metric_name, res in resolutions.items():
        facts_used.append(res["fact_id"])
        metrics[metric_name] = {
            "value": res["value"],
            "fact_id": res["fact_id"],
            "state": res["state"],
            "provider": res["provider"],
            "source_type": res["source_type"],
            "observed_at": res["observed_at"],
            "fresh": res["fresh"],
            "quality_label": res["quality_label"],
            "quality_score": res["quality_score"],
            "explicit_user_input": res["explicit_user_input"],
            "conflicts": res["conflicts"],
        }

    used = [m for m in metrics.values() if m.get("quality_score") is not None]
    if not used:
        quality_label, quality_score = E.Q_UNAVAILABLE, 0
    else:
        quality_score = min(m["quality_score"] for m in used)
        labels = {m["quality_label"] for m in used}
        if quality_score <= 0 or E.Q_UNAVAILABLE in labels:
            quality_label = E.Q_UNAVAILABLE
        elif E.Q_STALE in labels:
            quality_label = E.Q_STALE
        elif E.Q_CONFLICTING in labels:
            quality_label = E.Q_CONFLICTING
        elif E.Q_PARTIAL in labels:
            quality_label = E.Q_PARTIAL
        else:
            quality_label = E.Q_COMPLETE

    total_conflicts = sum(len(m.get("conflicts", [])) for m in metrics.values())
    return {
        "label": label,
        "facts_used": [f for f in facts_used if f],
        "metrics": metrics,
        "quality_label": quality_label,
        "quality_score": quality_score,
        "conflict_count": total_conflicts,
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
