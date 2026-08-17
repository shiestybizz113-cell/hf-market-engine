from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class AuthorityBasis(str, Enum):
    STANDING_AUTHORITY = "standing_authority"
    EXPLICIT_APPROVAL = "explicit_approval"
    SYSTEM_POLICY = "system_policy"


class ActionType(str, Enum):
    TRADE_ORDER = "trade_order"
    KEY_ROTATION = "key_rotation"
    KEY_REVOCATION = "key_revocation"
    TRAINING_EXTRACT_GENERATED = "training_extract_generated"


class EnvironmentMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    SIMULATED = "simulated"
    BACKTEST = "backtest"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class EvidenceStateLabel(str, Enum):
    VERIFIED = "VERIFIED"
    BUILT_NOT_YET_LIVE_VERIFIED = "BUILT_NOT_YET_LIVE_VERIFIED"
    NAMED_NOT_YET_BUILT = "NAMED_NOT_YET_BUILT"


class ConsentBasis(str, Enum):
    INTERNAL_OPERATIONAL = "internal_operational"
    USER_CONSENT = "user_consent"
    CONTRACT = "contract"


class RetentionPolicy(str, Enum):
    PURGE_AFTER_90D = "purge_after_90d"
    RETAIN_INDEFINITELY = "retain_indefinitely"


class TrainingDataLicense(str, Enum):
    NONE = "none"
    LICENSABLE_AGGREGATE_ONLY = "licensable_aggregate_only"
    INTERNAL_ALLOWED = "internal_allowed"


class Actor(BaseModel):
    agent_id: str
    agent_type: str
    operator_org_id: str


class Authority(BaseModel):
    authority_basis: AuthorityBasis
    scope: str


class Action(BaseModel):
    action_type: ActionType
    domain: str
    payload: Dict[str, Any]
    payload_schema_ref: Optional[str] = None


class EnvironmentState(BaseModel):
    mode: EnvironmentMode
    environment_id: str


class ClaimedOutcome(BaseModel):
    outcome_type: str
    outcome_payload: Dict[str, Any]


class Verification(BaseModel):
    status: VerificationStatus
    method: str
    verified_by: str
    evidence_state_label: EvidenceStateLabel


class Provenance(BaseModel):
    data_owner_org_id: str
    consent_basis: ConsentBasis
    retention_policy: RetentionPolicy
    training_data_license: TrainingDataLicense
    pii_present: bool = False


class GraphLinks(BaseModel):
    parent_receipt_ids: List[str] = Field(default_factory=list)


class Integrity(BaseModel):
    content_hash_sha256: str
    signature_ed25519: str
    signer_public_key_id: str
    signed_at: datetime


class Receipt(BaseModel):
    schema_version: str = "1.1"
    receipt_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Actor
    authority: Authority
    action: Action
    environment_state: EnvironmentState
    claimed_outcome: ClaimedOutcome
    verification: Verification
    provenance: Provenance
    graph_links: GraphLinks = Field(default_factory=GraphLinks)
    integrity: Optional[Integrity] = None
