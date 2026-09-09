#!/usr/bin/env python3
"""
Generate a stable Ed25519 signing key for Archisynapse receipts.

Run once per deployment. Store the output in your production .env as
ARCHISYNAPSE_SIGNING_KEY. Never commit it. Never rotate it casually —
rotating invalidates offline verification of all historical receipts
signed with the old key.

Usage:
    cd backend && python scripts/generate_signing_key.py
"""

import sys
from pathlib import Path

# Allow running from backend/ without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


def main() -> None:
    key = Ed25519PrivateKey.generate()
    priv_hex = key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    ).hex()
    pub_hex = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    print()
    print("=" * 70)
    print("  ARCHISYNAPSE v1.1 — SIGNING KEY GENERATED")
    print("=" * 70)
    print()
    print("Add this line to your production .env (never commit it):")
    print()
    print(f"  ARCHISYNAPSE_SIGNING_KEY={priv_hex}")
    print()
    print("Public key (safe to publish — auditors use this to verify receipts):")
    print()
    print(f"  {pub_hex}")
    print()
    print("-" * 70)
    print("WARNING: Store the private key in a secrets manager.")
    print("Losing it means all future receipts sign under a new identity.")
    print("Rotating it invalidates offline verification of historical receipts.")
    print("-" * 70)
    print()


if __name__ == "__main__":
    main()
