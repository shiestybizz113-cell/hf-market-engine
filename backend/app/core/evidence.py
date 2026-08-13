"""
Evidence Fact Fabric — the canonical, immutable provenance backbone.

Every number that enters the Capital Allocation Engine must first be an
evidence fact. Facts are append-only: a new observation creates a NEW fact
and (optionally) points ``supersedes`` at the fact it replaces. Old facts are
never overwritten, so history is always reconstructable.

Fact shape (all fields set on ingest):
    evidence_id        unique id
    domain             market | mining | hardware | gpu | energy | fleet
    metric             what is being measured (btc_price, asic_price, ...)
    subject_id         what the metric is about (BTC, S21 Pro, region, ...)
    value              numeric value
    unit               usd | usd_hr | usd_kwh | ths | mw | ...
    state              observed_live | user_assumption | simulation | unavailable
    provider           who reported it (coingecko, distributor, reference_catalog, ...)
    source_type        live_api | reference | distributor_quote | secondary_market |
                       user_purchase | user_input | contract | tariff | wholesale | ...
    source_reference   url / document ref
    observed_at        when the value was true
    ingested_at        when we stored it
    valid_until        observed_at + freshness TTL (expiry is the freshness policy)
    freshness_seconds  the TTL used
    region             optional region / node / locale
    confidence         0..1
    methodology        how the number was produced
    sha256             digest of the canonical payload (integrity check)
    supersedes         evidence_id this fact replaces (None for the first)
    raw_snapshot_ref   optional pointer to the raw provider payload
    user_id            None = system fact, else the operator who ingested it

Freshness policy is per (domain, metric) and, for operator-ingested feeds, per
source_type — a wholesale grid price expires much faster than a long-term
power contract, and an ASIC secondary-market quote faster than the reference
catalog. One global TTL is deliberately NOT used.

Source policy: every candidate fact is preserved. Selection ranks by evidence
state -> freshness -> source quality -> explicit user preference. Losing
sources are never deleted.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.core.database import get_db

# The only evidence states the platform may render.
OBSERVED_LIVE = "observed_live"
USER_ASSUMPTION = "user_assumption"
SIMULATION = "simulation"
UNAVAILABLE = "unavailable"

EVIDENCE_STATES = (OBSERVED_LIVE, USER_ASSUMPTION, SIMULATION, UNAVAILABLE)

# Data-quality labels surfaced in the UI / optimizer.
Q_COMPLETE = "COMPLETE"
Q_PARTIAL = "PARTIAL"
Q_STALE = "STALE"
Q_CONFLICTING = "CONFLICTING"
Q_UNAVAILABLE = "UNAVAILABLE"

# Relative disagreement above which two eligible facts are CONFLICTING.
CONFLICT_RELATIVE_PCT = 10.0

# --------------------------------------------------------------------------- #
# Freshness policy — per (domain, metric), with source_type overrides.
# --------------------------------------------------------------------------- #
FRESHNESS_DEFAULT_SECONDS = 86400  # 1 day fallback

FRESHNESS_POLICY: Dict[Tuple[str, str], int] = {
    # Live market observations expire fast.
    ("market", "btc_price"): 120,
    # Network data changes on ~10-minute retargets; 15 min is honest.
    ("mining", "network_hashrate"): 900,
    ("mining", "network_difficulty"): 900,
    # Consensus constants only change at a halving.
    ("mining", "block_subsidy"): 60 * 86400,
    # Hardware prices: indicative street/reference values move slowly.
    ("hardware", "asic_price"): 7 * 86400,
    ("hardware", "asic_hashrate"): 30 * 86400,
    ("hardware", "asic_power"): 30 * 86400,
    # GPU economics: capex is slow, a rental offer expires in hours.
    ("gpu", "gpu_capex"): 30 * 86400,
    ("gpu", "gpu_power"): 30 * 86400,
    ("gpu", "compute_offer"): 6 * 3600,
    # Energy prices: source-dependent; see source-type override below.
    ("energy", "power_price"): 3600,
    # Operator-owned assets persist until changed.
    ("fleet", "asset"): 365 * 86400,
}

# Source-type overrides: an energy *wholesale* price expires fast, a *contract*
# price is good for a month, a *tariff* for a week. Same for hardware quotes.
FRESHNESS_SOURCE_TYPE: Dict[str, int] = {
    "live_api": 300,
    "wholesale": 300,
    "tariff": 7 * 86400,
    "contract": 30 * 86400,
    "distributor_quote": 7 * 86400,
    "secondary_market": 3 * 86400,
    "reference": 30 * 86400,
    "manufacturer_reference": 30 * 86400,
    "user_purchase": 365 * 86400,
    "user_input": 90 * 86400,
    "user_assumption": 90 * 86400,
}

# Source quality (0..1) — used to break ties after state + freshness.
SOURCE_QUALITY: Dict[str, float] = {
    "coingecko": 0.9,
    "blockchain.info": 0.9,
    "user_purchase": 0.85,
    "contract": 0.8,
    "tariff": 0.8,
    "cloud_provider": 0.75,
    "wholesale": 0.75,
    "distributor_quote": 0.7,
    "manufacturer_reference": 0.6,
    "secondary_market": 0.6,
    "user_input": 0.5,
    "reference_catalog": 0.5,
    "user_assumption": 0.4,
    "demo": 0.1,
}

STATE_RANK = {
    OBSERVED_LIVE: 3,
    USER_ASSUMPTION: 2,
    SIMULATION: 1,
    UNAVAILABLE: 0,
}


@dataclass
class EvidenceFact:
    domain: str
    metric: str
    subject_id: str
    value: float
    unit: str
    state: str
    provider: str
    source_type: str
    source_reference: Optional[str] = None
    observed_at: Optional[datetime] = None
    region: Optional[str] = None
    confidence: Optional[float] = None
    methodology: Optional[str] = None
    user_id: Optional[str] = None
    raw_snapshot_ref: Optional[str] = None
    supersedes: Optional[str] = None
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    freshness_seconds: Optional[int] = None
    sha256: Optional[str] = None
    extra: Dict = field(default_factory=dict)


def freshness_seconds_for(domain: str, metric: str, source_type: str = "") -> int:
    if source_type in FRESHNESS_SOURCE_TYPE:
        return FRESHNESS_SOURCE_TYPE[source_type]
    return FRESHNESS_POLICY.get((domain, metric), FRESHNESS_DEFAULT_SECONDS)


def source_quality_for(provider: str) -> float:
    return SOURCE_QUALITY.get(provider, 0.3)


def _canonical(f: EvidenceFact) -> Dict:
    """Stable, non-identity payload used for the sha256 digest."""
    return {
        "domain": f.domain,
        "metric": f.metric,
        "subject_id": f.subject_id,
        "value": round(float(f.value), 6),
        "unit": f.unit,
        "state": f.state,
        "provider": f.provider,
        "source_type": f.source_type,
        "source_reference": f.source_reference,
        "region": f.region,
        "observed_at": (f.observed_at or f.ingested_at).isoformat(),
    }


def fact_sha256(f: EvidenceFact) -> str:
    payload = json.dumps(_canonical(f), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_doc(f: EvidenceFact) -> Dict:
    """Mongo-ready document. Immutable: nothing is ever $set back into it."""
    obs = f.observed_at or f.ingested_at
    ttl = freshness_seconds_for(f.domain, f.metric, f.source_type)
    valid_until = obs + timedelta(seconds=ttl)
    doc = {
        "evidence_id": f.evidence_id,
        "domain": f.domain,
        "metric": f.metric,
        "subject_id": f.subject_id,
        "value": float(f.value),
        "unit": f.unit,
        "state": f.state,
        "provider": f.provider,
        "source_type": f.source_type,
        "source_reference": f.source_reference,
        "observed_at": obs,
        "ingested_at": f.ingested_at,
        "valid_until": f.valid_until or valid_until,
        "freshness_seconds": f.freshness_seconds or ttl,
        "region": f.region,
        "confidence": f.confidence,
        "methodology": f.methodology,
        "sha256": f.sha256 or fact_sha256(f),
        "supersedes": f.supersedes,
        "raw_snapshot_ref": f.raw_snapshot_ref,
        "user_id": f.user_id,
    }
    if f.extra:
        doc["extra"] = f.extra
    return doc


async def ingest_fact(
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
    supersedes: Optional[str] = None,
    extra: Optional[Dict] = None,
    _db=None,
) -> str:
    """Append one immutable fact. Returns its evidence_id.

    Facts are NEVER overwritten. If this fact replaces an earlier one, set
    ``supersedes``; the old fact remains readable and graphed.
    """
    db = _db or get_db()
    f = EvidenceFact(
        domain=domain,
        metric=metric,
        subject_id=subject_id,
        value=value,
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
        supersedes=supersedes,
        extra=extra or {},
    )
    doc = to_doc(f)
    await db.evidence_facts.insert_one(doc)
    return f.evidence_id


def is_stale(doc: Dict, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    valid_until = doc.get("valid_until")
    if not valid_until:
        return True
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    return now > valid_until


def age_seconds(doc: Dict, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    obs = doc.get("observed_at") or doc.get("ingested_at")
    if obs is None:
        return float("inf")
    if obs.tzinfo is None:
        obs = obs.replace(tzinfo=timezone.utc)
    return max(0.0, (now - obs).total_seconds())


async def facts_for(
    *,
    domain: str,
    metric: str,
    subject_id: Optional[str] = None,
    user_id: Optional[str] = None,
    include_stale: bool = True,
    limit: int = 50,
    _db=None,
) -> List[Dict]:
    """All facts for a metric (append-only history preserved)."""
    db = _db or get_db()
    query: Dict = {"domain": domain, "metric": metric}
    if subject_id:
        query["subject_id"] = subject_id
    scope = [None]
    if user_id:
        scope.append(user_id)
    query["user_id"] = {"$in": scope}
    cursor = (
        db.evidence_facts.find(query)
        .sort("observed_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return out


async def eligible_facts(
    *,
    domain: str,
    metric: str,
    subject_id: Optional[str] = None,
    user_id: Optional[str] = None,
    _db=None,
) -> List[Dict]:
    """Facts that are fresh (not expired) and belong to the caller."""
    facts = await facts_for(
        domain=domain, metric=metric, subject_id=subject_id,
        user_id=user_id, include_stale=True, _db=_db,
    )
    now = datetime.now(timezone.utc)
    return [f for f in facts if not is_stale(f, now)]


def _material_disagreement(a: Dict, b: Dict) -> bool:
    va, vb = float(a["value"]), float(b["value"])
    denom = max(abs(va), abs(vb))
    if denom <= 1e-9:
        return False
    return abs(va - vb) / denom * 100.0 > CONFLICT_RELATIVE_PCT


def conflicts_in(facts: List[Dict]) -> List[Dict]:
    """Pairs of eligible facts for the same metric that disagree materially.

    Both sides are surfaced — losing sources are never hidden.
    """
    out = []
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            if _material_disagreement(facts[i], facts[j]):
                out.append({
                    "facts": [facts[i]["evidence_id"], facts[j]["evidence_id"]],
                    "values": [facts[i]["value"], facts[j]["value"]],
                    "providers": [facts[i]["provider"], facts[j]["provider"]],
                    "source_types": [facts[i]["source_type"], facts[j]["source_type"]],
                    "disagreement_pct": round(
                        abs(facts[i]["value"] - facts[j]["value"]) /
                        max(abs(facts[i]["value"]), abs(facts[j]["value"])) * 100.0, 1
                    ),
                })
    return out


def select_best_fact(facts: List[Dict], explicit_user_input: bool = False) -> Optional[Dict]:
    """Rank by evidence state -> freshness -> source quality. All candidates are
    preserved in the caller's trace; this only picks the winner."""
    if not facts:
        return None

    def rank(f):
        state = STATE_RANK.get(f.get("state"), 0)
        freshness = max(0.0, 1.0 - (age_seconds(f) / max(1.0, f.get("freshness_seconds", 1.0))))
        quality = source_quality_for(f.get("provider", ""))
        # Explicit operator input is the strongest signal when present.
        if explicit_user_input and f.get("provider") == "user_input":
            state = 10
        return (state, freshness, quality, f.get("observed_at") or datetime.min)

    return max(facts, key=rank)


def quality_for_facts(facts: List[Dict]) -> Tuple[str, int]:
    """Data-quality label + 0..100 score for a resolution.

    COMPLETE       a fresh fact was used, no conflicts
    CONFLICTING    fresh facts exist but disagree materially (both shown)
    PARTIAL        the value used was a low-priority source / assumption
    STALE          only expired facts exist (value used, flagged stale)
    UNAVAILABLE    nothing at all
    """
    if not facts:
        return Q_UNAVAILABLE, 0
    conflicts = conflicts_in(facts)
    if conflicts:
        return Q_CONFLICTING, 60
    best = select_best_fact(facts)
    fresh = not is_stale(best)
    if fresh:
        if best.get("state") == OBSERVED_LIVE:
            return Q_COMPLETE, 95
        # assumption / reference / user data is legitimate but not observed-live.
        return Q_COMPLETE, 70
    return Q_STALE, 35


def summarize_resolution(
    facts: List[Dict],
    explicit_user_input: bool = False,
) -> Dict:
    """Public shape for one resolved metric: value + winner + full trace."""
    conflicts = conflicts_in(facts)
    best = select_best_fact(facts, explicit_user_input)
    label, score = quality_for_facts(facts)
    if best is None:
        label = Q_UNAVAILABLE
    elif label == Q_COMPLETE and explicit_user_input:
        label = Q_PARTIAL
    return {
        "value": best.get("value") if best else None,
        "fact_id": best.get("evidence_id") if best else None,
        "state": best.get("state") if best else UNAVAILABLE,
        "provider": best.get("provider") if best else None,
        "source_type": best.get("source_type") if best else None,
        "source_reference": best.get("source_reference") if best else None,
        "observed_at": best.get("observed_at") if best else None,
        "age_seconds": round(age_seconds(best), 1) if best else None,
        "fresh": bool(best and not is_stale(best)),
        "quality_label": label,
        "quality_score": score,
        "explicit_user_input": explicit_user_input,
        "candidates": [
            {
                "fact_id": f["evidence_id"],
                "value": f["value"],
                "state": f["state"],
                "provider": f["provider"],
                "source_type": f["source_type"],
                "observed_at": f["observed_at"],
                "fresh": not is_stale(f),
            }
            for f in facts
        ],
        "conflicts": conflicts,
    }


async def get_fact(evidence_id: str, _db=None) -> Optional[Dict]:
    db = _db or get_db()
    doc = await db.evidence_facts.find_one({"evidence_id": evidence_id})
    if doc:
        doc.pop("_id", None)
    return doc


# --------------------------------------------------------------------------- #
# Proof graph
# --------------------------------------------------------------------------- #
async def build_proof_graph(receipt_id: str, user_id: str, _db=None) -> Dict:
    """Reconstruct receipt -> evidence facts -> sources for the proof drawer.

    Works for any receipt in ``mining_receipts`` (mining and capital receipts
    share that collection). Facts referenced by the receipt are pulled in, and
    per-lane fact usage from ``lanes_evidence`` is turned into edges so the
    drawer can show exactly which facts each calculation consumed.
    """
    db = _db or get_db()
    receipt = await db.mining_receipts.find_one(
        {"_id": receipt_id, "user_id": user_id}
    )
    if not receipt:
        return None

    receipt.pop("system_prompt", None)
    receipt.pop("_id", None)

    ids = list(dict.fromkeys(receipt.get("evidence_ids") or []))
    facts: List[Dict] = []
    for fid in ids:
        fact = await get_fact(fid, db)
        if fact:
            fact["age_seconds"] = round(age_seconds(fact), 1)
            fact["fresh"] = not is_stale(fact)
            facts.append(fact)

    lanes_evidence = receipt.get("lanes_evidence") or {}
    nodes = [
        {"kind": "receipt", "id": receipt_id, "analysis_type": receipt.get("analysis_type")},
    ]
    for fact in facts:
        nodes.append({
            "kind": "fact",
            "id": fact["evidence_id"],
            "domain": fact["domain"],
            "metric": fact["metric"],
            "subject_id": fact["subject_id"],
            "value": fact["value"],
            "unit": fact["unit"],
            "state": fact["state"],
            "provider": fact["provider"],
            "source_type": fact["source_type"],
        })
    edges = [{"from": "receipt:" + receipt_id, "to": "fact:" + f["evidence_id"]} for f in facts]
    for lane_key, lane in lanes_evidence.items():
        nodes.append({"kind": "lane", "id": lane_key, "label": lane.get("label", lane_key)})
        for fid in lane.get("facts_used", []):
            edges.append({"from": "lane:" + lane_key, "to": "fact:" + fid})

    return {
        "receipt": receipt,
        "facts": facts,
        "lanes_evidence": lanes_evidence,
        "graph": {"nodes": nodes, "edges": edges},
    }
