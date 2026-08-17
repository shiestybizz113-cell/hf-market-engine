from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .crypto import SigningKey
from .schema import (
    Action,
    ActionType,
    Actor,
    Authority,
    AuthorityBasis,
    ClaimedOutcome,
    ConsentBasis,
    EnvironmentMode,
    EnvironmentState,
    EvidenceStateLabel,
    GraphLinks,
    Provenance,
    Receipt,
    RetentionPolicy,
    TrainingDataLicense,
    Verification,
    VerificationStatus,
)


class TrustStatus(str, Enum):
    VERIFIED = "verified"
    DISPUTED = "disputed"


class TrustOverlay(BaseModel):
    status: TrustStatus
    quarantine_reason: Optional[str] = None
    changed_at: datetime
    source_receipt_id: Optional[str] = None


class ReceiptGraph:
    """In-memory v1.1 reference graph.

    HF integration persists signed receipts separately in Mongo. This class remains
    useful for deterministic lifecycle behavior and the standalone regression demo.
    """

    def __init__(self):
        self._receipts: Dict[str, Receipt] = {}
        self.key_registry: Dict[str, str] = {}
        self._overlays: Dict[str, TrustOverlay] = {}

    def register_key(self, key_id: str, public_key: str) -> None:
        existing = self.key_registry.get(key_id)
        if existing and existing != public_key:
            raise ValueError(f"Key id {key_id} is already registered with different material.")
        self.key_registry[key_id] = public_key

    def add(self, receipt: Receipt) -> None:
        if receipt.receipt_id in self._receipts:
            raise ValueError(f"Duplicate receipt id: {receipt.receipt_id}")
        self._receipts[receipt.receipt_id] = receipt.model_copy(deep=True)

    def get(self, receipt_id: str) -> Receipt:
        receipt = self._receipts.get(receipt_id)
        if receipt is None:
            raise KeyError(receipt_id)
        return receipt.model_copy(deep=True)

    def all(self) -> List[Receipt]:
        return [r.model_copy(deep=True) for r in self._receipts.values()]

    def effective_status(self, receipt_id: str) -> TrustOverlay:
        if receipt_id not in self._receipts:
            raise KeyError(receipt_id)
        overlay = self._overlays.get(receipt_id)
        if overlay:
            return overlay.model_copy(deep=True)
        return TrustOverlay(
            status=TrustStatus.VERIFIED,
            changed_at=self._receipts[receipt_id].created_at,
        )

    def rotate_key(
        self,
        root_key: SigningKey,
        outgoing_key: SigningKey,
        incoming_key: SigningKey,
    ) -> Receipt:
        # root_key is intentionally accepted as the trust anchor for the lifecycle,
        # while v1.1 preserves the design choice that the outgoing key signs the
        # handoff. Root-signed revocation remains the recovery path.
        self.register_key(root_key.key_id, root_key.public_key)
        self.register_key(outgoing_key.key_id, outgoing_key.public_key)
        self.register_key(incoming_key.key_id, incoming_key.public_key)

        receipt = Receipt(
            actor=Actor(
                agent_id="receipt-graph-key-rotator",
                agent_type="governance_service",
                operator_org_id="empire-1",
            ),
            authority=Authority(
                authority_basis=AuthorityBasis.SYSTEM_POLICY,
                scope="receipt_graph.signing_key_rotation",
            ),
            action=Action(
                action_type=ActionType.KEY_ROTATION,
                domain="empire_1.receipt_graph.pki",
                payload={
                    "outgoing_key_id": outgoing_key.key_id,
                    "incoming_key_id": incoming_key.key_id,
                    "root_key_id": root_key.key_id,
                },
            ),
            environment_state=EnvironmentState(
                mode=EnvironmentMode.SIMULATED,
                environment_id="receipt-graph-reference",
            ),
            claimed_outcome=ClaimedOutcome(
                outcome_type="key_rotation",
                outcome_payload={"incoming_key_registered": True},
            ),
            verification=Verification(
                status=VerificationStatus.VERIFIED,
                method="cryptographic_key_handoff",
                verified_by="receipt_graph.rotate_key",
                evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
            ),
            provenance=Provenance(
                data_owner_org_id="empire-1",
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
                training_data_license=TrainingDataLicense.NONE,
                pii_present=False,
            ),
        )
        signed = outgoing_key.sign_receipt(receipt)
        self.add(signed)
        return signed

    def revoke_key(
        self,
        root_key: SigningKey,
        *,
        revoked_key_id: str,
        window_start: str,
        window_end: str,
        reason: str,
    ) -> Receipt:
        self.register_key(root_key.key_id, root_key.public_key)
        start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        receipt = Receipt(
            actor=Actor(
                agent_id="receipt-graph-root-authority",
                agent_type="governance_service",
                operator_org_id="empire-1",
            ),
            authority=Authority(
                authority_basis=AuthorityBasis.SYSTEM_POLICY,
                scope="receipt_graph.signing_key_revocation",
            ),
            action=Action(
                action_type=ActionType.KEY_REVOCATION,
                domain="empire_1.receipt_graph.pki",
                payload={
                    "revoked_key_id": revoked_key_id,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "reason": reason,
                },
            ),
            environment_state=EnvironmentState(
                mode=EnvironmentMode.SIMULATED,
                environment_id="receipt-graph-reference",
            ),
            claimed_outcome=ClaimedOutcome(
                outcome_type="key_revoked",
                outcome_payload={"revoked_key_id": revoked_key_id},
            ),
            verification=Verification(
                status=VerificationStatus.VERIFIED,
                method="root_signed_revocation",
                verified_by=root_key.key_id,
                evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
            ),
            provenance=Provenance(
                data_owner_org_id="empire-1",
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
                training_data_license=TrainingDataLicense.NONE,
                pii_present=False,
            ),
        )
        signed = root_key.sign_receipt(receipt)
        self.add(signed)

        for receipt_id, existing in self._receipts.items():
            if existing.integrity is None:
                continue
            if existing.integrity.signer_public_key_id != revoked_key_id:
                continue
            if start <= existing.created_at <= end:
                self._overlays[receipt_id] = TrustOverlay(
                    status=TrustStatus.DISPUTED,
                    quarantine_reason=reason,
                    changed_at=now,
                    source_receipt_id=signed.receipt_id,
                )
        return signed


def build_training_extract(
    signing_key: SigningKey,
    source_receipt: Receipt,
    feature_payload: Dict[str, Any],
    source_scheduled_purge_date: Optional[str] = None,
) -> Receipt:
    if source_receipt.provenance.training_data_license == TrainingDataLicense.NONE:
        raise PermissionError("Source receipt does not permit training extraction.")

    extract = Receipt(
        actor=Actor(
            agent_id="receipt-graph-training-extractor",
            agent_type="data_governance_service",
            operator_org_id=source_receipt.actor.operator_org_id,
        ),
        authority=Authority(
            authority_basis=AuthorityBasis.SYSTEM_POLICY,
            scope="training_extract.deidentified",
        ),
        action=Action(
            action_type=ActionType.TRAINING_EXTRACT_GENERATED,
            domain="empire_1.receipt_graph.training",
            payload={"features": feature_payload},
        ),
        environment_state=source_receipt.environment_state.model_copy(deep=True),
        claimed_outcome=ClaimedOutcome(
            outcome_type="deidentified_training_extract",
            outcome_payload={
                "features": feature_payload,
                "source_scheduled_purge_date": source_scheduled_purge_date,
            },
        ),
        verification=Verification(
            status=VerificationStatus.VERIFIED,
            method="deterministic_deidentification_transform",
            verified_by="receipt_graph.build_training_extract",
            evidence_state_label=EvidenceStateLabel.BUILT_NOT_YET_LIVE_VERIFIED,
        ),
        provenance=Provenance(
            data_owner_org_id=source_receipt.provenance.data_owner_org_id,
            consent_basis=source_receipt.provenance.consent_basis,
            retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
            training_data_license=TrainingDataLicense.NONE,
            pii_present=False,
        ),
        graph_links=GraphLinks(parent_receipt_ids=[source_receipt.receipt_id]),
    )
    return signing_key.sign_receipt(extract)
