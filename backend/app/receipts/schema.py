"""
Empire-1 Action Receipt — schema v1.1

Implements the Receipt v1 JSON Schema plus the v1.1 addendum
(key_rotation, key_revocation, schema_registration, schema_deprecation,
training_extract_generated) as real, validated Python models.

This is a reference implementation meant to be dropped into hf-market-engine
(or any FastAPI service) as an additive module — it does not touch or
assume anything about the host application's existing models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums (kept as plain str enums so they serialize identically to the
# JSON Schema's `enum` constraints)
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    TRADE_ORDER = "trade_order"
    NEGOTIATION_OFFER = "negotiation_offer"
    SPEND = "spend"
    HIRE = "hire"
    FIRE = "fire"
    APPROVE = "approve"
    CONTRACT_EXECUTE = "contract_execute"
    RESOURCE_ALLOCATE = "resource_allocate"
    # v1.1 additions — infrastructure/meta receipt types
    KEY_ROTATION = "key_rotation"
    KEY_REVOCATION = "key_revocation"
    SCHEMA_REGISTRATION = "schema_registration"
    SCHEMA_DEPRECATION = "schema_deprecation"
    TRAINING_EXTRACT_GENERATED = "training_extract_generated"
    OTHER = "other"


class EnvironmentMode(str, Enum):
    LIVE = "live"
    PAPER = "paper"
    SIMULATED = "simulated"
    BACKTEST = "backtest"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class EvidenceStateLabel(str, Enum):
    VERIFIED = "VERIFIED"
    BUILT_NOT_YET_LIVE_VERIFIED = "BUILT_NOT_YET_LIVE_VERIFIED"
    NAMED_NOT_YET_BUILT = "NAMED_NOT_YET_BUILT"


class AuthorityBasis(str, Enum):
    USER_DELEGATED = "user_delegated"
    POLICY_ENGINE_APPROVED = "policy_engine_approved"
    STANDING_AUTHORITY = "standing_authority"
    SELF_ATTESTED_NONE = "self_attested_none"


class ConsentBasis(str, Enum):
    CONTRACTUAL = "contractual"
    USER_CONSENTED = "user_consented"
    INTERNAL_OPERATIONAL = "internal_operational"
    REGULATORY_REQUIRED = "regulatory_required"


class RetentionPolicy(str, Enum):
    RETAIN_INDEFINITELY = "retain_indefinitely"
    RETAIN_7YR = "retain_7yr"
    PURGE_AFTER_90D = "purge_after_90d"
    PURGE_ON_REQUEST = "purge_on_request"


class TrainingDataLicense(str, Enum):
    NONE = "none"
    INTERNAL_ONLY = "internal_only"
    LICENSABLE_AGGREGATE_ONLY = "licensable_aggregate_only"
    LICENSABLE_FULL = "licensable_full"


class SignatureAlgorithm(str, Enum):
    ED25519 = "Ed25519"
    ECDSA_P256 = "ECDSA-P256"


# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

class Actor(BaseModel):
    agent_id: str
    agent_type: str
    operator_org_id: str


class Authority(BaseModel):
    authority_receipt_id: str | None = None
    authority_basis: AuthorityBasis
    scope: str


class Action(BaseModel):
    action_type: ActionType
    domain: str
    payload: dict[str, Any]
    payload_schema_ref: str | None = None


class EnvironmentState(BaseModel):
    mode: EnvironmentMode
    environment_id: str


class ClaimedOutcome(BaseModel):
    outcome_type: str
    outcome_payload: dict[str, Any]
    outcome_timestamp: str = Field(default_factory=now_iso)


class Verification(BaseModel):
    status: VerificationStatus
    method: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    evidence_state_label: EvidenceStateLabel
    quarantine_reason: str | None = None  # v1.1 addition


class Provenance(BaseModel):
    data_owner_org_id: str
    consent_basis: ConsentBasis
    retention_policy: RetentionPolicy
    training_data_license: TrainingDataLicense
    pii_present: bool
    training_extract_id: str | None = None  # v1.1 addition


class GraphLinks(BaseModel):
    parent_receipt_ids: list[str] = Field(default_factory=list)
    related_receipt_ids: list[str] = Field(default_factory=list)


class Integrity(BaseModel):
    canonical_hash: str
    signature: str
    signer_public_key_id: str
    signature_algorithm: SignatureAlgorithm


# ---------------------------------------------------------------------------
# Top-level Receipt
# ---------------------------------------------------------------------------

class Receipt(BaseModel):
    receipt_id: str = Field(default_factory=new_uuid)
    schema_version: str = "1.1"
    created_at: str = Field(default_factory=now_iso)

    actor: Actor
    authority: Authority
    action: Action
    environment_state: EnvironmentState
    claimed_outcome: ClaimedOutcome
    verification: Verification
    provenance: Provenance
    graph_links: GraphLinks = Field(default_factory=GraphLinks)

    # integrity is attached after signing — absent on an unsigned draft
    integrity: Integrity | None = None

    def unsigned_dict(self) -> dict[str, Any]:
        """Everything except the integrity block — this is what gets hashed and signed."""
        data = self.model_dump(mode="json")
        data.pop("integrity", None)
        return data
