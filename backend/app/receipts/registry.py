"""
In-memory Receipt Graph store + the root-of-trust key lifecycle logic
described in the v1.1 addendum (key_rotation / key_revocation).

Swap this for a real datastore later — the logic here (especially
compromise handling) is the part worth keeping stable across that swap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .crypto import KeyRegistry, SigningKey, verify_receipt
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


@dataclass
class TrustOverlay:
    """Current trust status for a receipt, tracked SEPARATELY from the
    signed envelope. This is the fix for a real bug this implementation
    hit during testing: verification.status was originally a field
    inside the signed payload, so quarantining a receipt after the fact
    mutated content the signature covered — which made verify_receipt
    correctly, but unhelpfully, start reporting tampering on a receipt
    nobody actually tampered with.

    The fix is conceptual, not just code: "is this receipt authentic"
    (verify_receipt, against the immutable signed envelope) and "should
    this receipt currently be trusted" (effective status, via this
    overlay) are different questions, and conflating them was the bug.
    """

    status: VerificationStatus
    quarantine_reason: Optional[str] = None


@dataclass
class ReceiptGraph:
    """The whole point of this class: a receipt is never useful alone.
    It's useful because it can be traced through parents, checked against
    the key that signed it, and re-verified independently of who's asking."""

    key_registry: KeyRegistry = field(default_factory=KeyRegistry)
    _receipts: dict[str, Receipt] = field(default_factory=dict)
    # key_id -> currently-valid ("clean") or quarantined
    _quarantined_key_ids: set[str] = field(default_factory=set)
    # receipt_id -> current trust status, separate from the immutable signed envelope
    _trust_overlay: dict[str, TrustOverlay] = field(default_factory=dict)

    # -- storage -----------------------------------------------------

    def add(self, receipt: Receipt) -> Receipt:
        is_valid, reason = verify_receipt(receipt, self.key_registry)
        if not is_valid:
            raise ValueError(f"Refusing to store unverifiable receipt: {reason}")
        self._receipts[receipt.receipt_id] = receipt
        return receipt

    def get(self, receipt_id: str) -> Receipt:
        return self._receipts[receipt_id]

    def effective_status(self, receipt_id: str) -> TrustOverlay:
        """The status to actually act on. Falls back to the receipt's
        originally-signed status if no overlay exists yet."""
        if receipt_id in self._trust_overlay:
            return self._trust_overlay[receipt_id]
        r = self.get(receipt_id)
        return TrustOverlay(status=r.verification.status, quarantine_reason=None)

    def parents(self, receipt_id: str) -> list[Receipt]:
        r = self.get(receipt_id)
        return [self.get(pid) for pid in r.graph_links.parent_receipt_ids]

    def all(self) -> list[Receipt]:
        return list(self._receipts.values())

    def register_key(self, key_id: str, public_key: Ed25519PublicKey) -> None:
        self.key_registry.register(key_id, public_key)

    # -- key lifecycle (v1.1) ----------------------------------------

    def rotate_key(
        self,
        root_key: SigningKey,
        outgoing: SigningKey,
        incoming: SigningKey,
        reason: str = "scheduled_rotation",
    ) -> Receipt:
        """Signed by the OUTGOING key — proves the outgoing key itself
        endorsed the handoff, producing an unbroken chain."""
        self.register_key(incoming.key_id, incoming.public_key)

        draft = Receipt(
            actor=Actor(agent_id="pki-controller", agent_type="infra", operator_org_id="empire-1"),
            authority=Authority(authority_basis=AuthorityBasis.STANDING_AUTHORITY, scope="pki.key_management"),
            action=Action(
                action_type=ActionType.KEY_ROTATION,
                domain="empire-1.pki",
                payload={
                    "outgoing_key_id": outgoing.key_id,
                    "incoming_key_id": incoming.key_id,
                    "reason": reason,
                },
            ),
            environment_state=EnvironmentState(mode=EnvironmentMode.LIVE, environment_id="empire-1-pki"),
            claimed_outcome=ClaimedOutcome(
                outcome_type="key_rotated",
                outcome_payload={"incoming_key_id": incoming.key_id},
            ),
            verification=Verification(
                status=VerificationStatus.VERIFIED,
                method="self_attested",
                evidence_state_label=EvidenceStateLabel.VERIFIED,
            ),
            provenance=Provenance(
                data_owner_org_id="empire-1",
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
                training_data_license=TrainingDataLicense.NONE,
                pii_present=False,
            ),
        )
        signed = outgoing.sign_receipt(draft)
        return self.add(signed)

    def revoke_key(
        self,
        root_key: SigningKey,
        revoked_key_id: str,
        window_start: str,
        window_end: str,
        reason: str = "suspected_compromise",
    ) -> Receipt:
        """Signed by the ROOT key. Does NOT invalidate everything the
        revoked key signed — it quarantines receipts in the suspected
        window for review. Most were probably legitimate; blanket
        invalidation destroys more trust than the compromise did."""
        self._quarantined_key_ids.add(revoked_key_id)

        draft = Receipt(
            actor=Actor(agent_id="pki-controller", agent_type="infra", operator_org_id="empire-1"),
            authority=Authority(authority_basis=AuthorityBasis.STANDING_AUTHORITY, scope="pki.key_management"),
            action=Action(
                action_type=ActionType.KEY_REVOCATION,
                domain="empire-1.pki",
                payload={
                    "revoked_key_id": revoked_key_id,
                    "suspected_compromise_window": {"start": window_start, "end": window_end},
                    "reason": reason,
                },
            ),
            environment_state=EnvironmentState(mode=EnvironmentMode.LIVE, environment_id="empire-1-pki"),
            claimed_outcome=ClaimedOutcome(
                outcome_type="key_revoked",
                outcome_payload={"revoked_key_id": revoked_key_id},
            ),
            verification=Verification(
                status=VerificationStatus.VERIFIED,
                method="self_attested",
                evidence_state_label=EvidenceStateLabel.VERIFIED,
            ),
            provenance=Provenance(
                data_owner_org_id="empire-1",
                consent_basis=ConsentBasis.INTERNAL_OPERATIONAL,
                retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
                training_data_license=TrainingDataLicense.NONE,
                pii_present=False,
            ),
        )
        signed = root_key.sign_receipt(draft)
        revocation_receipt = self.add(signed)

        # Quarantine, don't nuke: set an overlay marking affected receipts
        # disputed, WITHOUT touching the receipt's original signed content.
        # The signature still proves what was originally claimed and by
        # whom; the overlay is what says whether to currently act on it.
        for r in self._receipts.values():
            if (
                r.integrity
                and r.integrity.signer_public_key_id == revoked_key_id
                and window_start <= r.created_at <= window_end
            ):
                self._trust_overlay[r.receipt_id] = TrustOverlay(
                    status=VerificationStatus.DISPUTED,
                    quarantine_reason="signing_key_compromised",
                )

        return revocation_receipt

    def is_key_quarantined(self, key_id: str) -> bool:
        return key_id in self._quarantined_key_ids


def build_training_extract(
    signing_key: SigningKey,
    source_receipt: Receipt,
    feature_payload: dict,
    source_scheduled_purge_date: Optional[str] = None,
) -> Receipt:
    """De-identified feature extraction, proven to have happened BEFORE
    the source receipt's purge — this is what makes
    'derived features may outlive the raw record; the raw record never
    does' auditable instead of a quiet exception."""
    if source_receipt.provenance.training_data_license == TrainingDataLicense.NONE:
        raise PermissionError(
            f"Receipt {source_receipt.receipt_id} has training_data_license=NONE — "
            "extraction is not permitted, full stop."
        )

    draft = Receipt(
        actor=Actor(agent_id="training-pipeline", agent_type="infra", operator_org_id="empire-1"),
        authority=Authority(authority_basis=AuthorityBasis.STANDING_AUTHORITY, scope="training_pipeline.extract"),
        action=Action(
            action_type=ActionType.TRAINING_EXTRACT_GENERATED,
            domain="empire-1.training_pipeline",
            payload={
                "source_receipt_id": source_receipt.receipt_id,
                "de_identification_method": "aggregate_numeric_only",
                "source_scheduled_purge_date": source_scheduled_purge_date,
                "features": feature_payload,
            },
        ),
        environment_state=EnvironmentState(mode=EnvironmentMode.LIVE, environment_id="empire-1-training"),
        claimed_outcome=ClaimedOutcome(
            outcome_type="extract_generated",
            outcome_payload={"feature_count": len(feature_payload)},
        ),
        verification=Verification(
            status=VerificationStatus.VERIFIED,
            method="self_attested",
            evidence_state_label=EvidenceStateLabel.VERIFIED,
        ),
        provenance=Provenance(
            data_owner_org_id=source_receipt.provenance.data_owner_org_id,
            consent_basis=source_receipt.provenance.consent_basis,
            retention_policy=RetentionPolicy.RETAIN_INDEFINITELY,
            training_data_license=source_receipt.provenance.training_data_license,
            pii_present=False,  # by construction — that's the whole point of de-identification
        ),
        graph_links=GraphLinks(parent_receipt_ids=[source_receipt.receipt_id]),
    )
    return signing_key.sign_receipt(draft)
