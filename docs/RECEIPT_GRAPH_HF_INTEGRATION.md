# HF Market Engine × Receipt Graph v1.1

This checkpoint integrates Receipt v1.1 into the existing **paper-trade open** path without replacing the FastAPI app, paper-trade model, risk engine, market-data service, or Mongo deployment.

## What happens now

When `PaperTradingEngine.open_trade()` passes the existing risk and price checks:

1. The engine builds the normal paper-trade record with its existing UUID.
2. Receipt v1.1 builds and Ed25519-signs an immutable paper-trade receipt referencing that trade id.
3. The paper-trade record is inserted into `paper_trades` with the receipt id attached.
4. The full signed envelope is inserted into the durable `receipts` Mongo collection.
5. The service **re-reads the receipt from Mongo**, loads the signer's public key from the separate `receipt_keys` collection, recomputes canonical JSON + SHA-256, and verifies the Ed25519 signature.
6. Only after that verification succeeds is the paper trade marked `receipt_status=verified` and returned as successful.

If receipt persistence or verification fails, the paper trade is retained as `status=evidence_failed` / `receipt_status=failed`. It is not silently returned as an active, proven position.

That failure behavior is deliberate: Phase 1 Mongo is a standalone node, so cross-document transactions are not available by default. The code preserves the contradiction instead of deleting history or pretending atomicity.

## Receipt boundaries

The emitted receipt says exactly what the engine can currently prove:

- environment mode: `paper`
- evidence label: `BUILT_NOT_YET_LIVE_VERIFIED`
- action: paper trade order / position open
- source trade id and opening price
- actor: `hf-market-engine.paper-trading-engine`
- authority: scoped standing authority for the current user
- provenance: Empire-1 internal operational data
- retention: purge after 90 days
- training license: aggregate-only

This integration does **not** claim that a broker or exchange filled a live order.

## Key custody

In paper mode, if no receipt key variables are configured, the service creates a fresh in-process Ed25519 signing key on startup and persists the public key in `receipt_keys`.

Optional development configuration:

```env
RECEIPT_SIGNING_KEY_ID=empire-1-hf-paper-...
RECEIPT_SIGNING_PRIVATE_KEY_B64=...
```

Never commit private-key material.

Before Receipt Graph is allowed to support real-stakes/live actions, private-key custody must move to a real KMS/HSM or equivalent external signer. This PR does not claim that work is done.

## Regression suite

From `backend/`:

```bash
python3 -m unittest discover -s tests -p 'test_receipts.py'
```

The seven tests cover:

1. signed receipt verification
2. canonical-hash tamper detection
3. signing-key rotation chain
4. root-signed revocation and separate trust overlay
5. clean-key receipts remaining trusted
6. training extract lineage / de-identification marker
7. hard refusal when training license is `NONE`

## Independent persisted verification

After creating a paper trade, take its stored `receipt_id` and run a second process:

```bash
cd backend
python3 scripts/verify_receipt.py <receipt_id>
```

The verifier does not use the signing private key. It reads the signed receipt and public key from Mongo and independently recomputes the canonical hash and Ed25519 verification.

Success looks like:

```text
receipt_id: ...
source_trade_id: ...
signer_key_id: ...
environment: paper
valid: True
reason: signature and canonical hash valid
```

## What this checkpoint proves

It proves the integration contract in code: an HF paper trade can emit a durable signed receipt that can be retrieved and independently cryptographically verified without changing the existing order model.

## Still open before real stakes

- KMS/HSM-backed private-key custody
- a production key-rotation/revocation operator workflow
- cross-document atomicity (replica-set transaction or an equivalent durable write design)
- independent broker/execution reconciliation for anything labeled live
- production monitoring and alerting for receipt persistence/verification failures
