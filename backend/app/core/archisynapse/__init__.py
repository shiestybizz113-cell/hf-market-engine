"""
Archisynapse v1.1 — AI Governance Receipt Layer for hf-market-engine.

Public API:
    build_receipt(...)     → SignedReceipt (not yet persisted)
    persist_receipt(...)   → (receipt_id, persisted: bool)
    get_receipt(...)       → SignedReceipt | None
    list_receipts(...)     → List[dict]
    verify_receipt(...)    → bool
    get_public_key_hex()   → str
"""

from app.core.archisynapse.registry import (
    build_receipt,
    persist_receipt,
    get_receipt,
    list_receipts,
    verify_receipt,
)
from app.core.archisynapse.crypto import get_public_key_hex
from app.core.archisynapse.schema import SignedReceipt, ReceiptPayload

__all__ = [
    "build_receipt",
    "persist_receipt",
    "get_receipt",
    "list_receipts",
    "verify_receipt",
    "get_public_key_hex",
    "SignedReceipt",
    "ReceiptPayload",
]
