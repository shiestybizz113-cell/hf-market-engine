#!/usr/bin/env python3
"""Independently verify a persisted Receipt v1.1 from Mongo.

Run from backend/:
    python3 scripts/verify_receipt.py <receipt_id>

This process does not need the signing private key. It reconstructs the signed
receipt from Mongo, loads only the persisted public key, recomputes canonical
JSON + SHA-256, and verifies the Ed25519 signature.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from receipts import Receipt, verify_receipt


async def verify_one(receipt_id: str) -> int:
    await connect_to_mongo()
    try:
        db = get_db()
        stored = await db.receipts.find_one({"_id": receipt_id})
        if not stored:
            print(f"NOT FOUND: {receipt_id}")
            return 2

        receipt = Receipt.model_validate(stored["receipt"])
        if receipt.integrity is None:
            print("INVALID: receipt has no integrity envelope")
            return 1

        key_id = receipt.integrity.signer_public_key_id
        key_doc = await db.receipt_keys.find_one({"_id": key_id})
        if not key_doc:
            print(f"INVALID: public key is missing for {key_id}")
            return 1

        valid, reason = verify_receipt(receipt, {key_id: key_doc["public_key"]})
        print(f"receipt_id: {receipt.receipt_id}")
        print(f"source_trade_id: {stored.get('source_trade_id')}")
        print(f"signer_key_id: {key_id}")
        print(f"environment: {receipt.environment_state.mode.value}")
        print(f"valid: {valid}")
        print(f"reason: {reason}")
        return 0 if valid else 1
    finally:
        await close_mongo_connection()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 scripts/verify_receipt.py <receipt_id>")
        return 2
    return asyncio.run(verify_one(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
