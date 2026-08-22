# Public deployment — Capital Command Center V2

This is the supported public deployment path for `hf-market-engine`.

## What ships

- Caddy: public TLS edge on 80/443.
- Frontend: nginx-served React/Vite SPA.
- Backend: FastAPI/Uvicorn, multiple workers supported.
- MongoDB: durable users, assets, evidence facts, provider snapshots, receipts.
- Redis: shared rate limits + infrastructure provider refresh gates.
- Capital optimizer: proposal-only. No trade/spend/deploy action exists on the Capital surface.

## 1. Prepare configuration

```bash
cp .env.example .env
```

Required for production:

- `APP_DOMAIN`: public hostname pointed at this server.
- `SECRET_KEY`: random value at least 32 characters.
- `CORS_ORIGINS`: exact HTTPS application origin(s), never `*`.
- Mongo root/app credentials.

Choose `MARKET_DATA_MODE` deliberately:

- `demo` = explicitly labeled simulation/demo data.
- `live` = real market providers only. Missing live inputs stay missing.

Optional Capital V2 observed infrastructure feeds:

- `HARDWARE_OFFERS_URL`
- `GPU_OFFERS_URL`
- `ENERGY_PRICES_URL`

If those are blank, the product still runs, but ASIC/GPU catalog values remain assumptions/reference and energy market context remains unavailable. Do not describe those lanes as live.

## 2. Verify before exposing traffic

From the repository root:

```bash
bash scripts/verify_public_release.sh
```

That check intentionally avoids the root-owned frontend `dist/` and Python `__pycache__` artifacts encountered during local development. It verifies backend syntax/tests/imports, TypeScript, Vite production build, production Compose configuration/images, and locked governance assertions.

Do not mark the release verified unless the script ends with:

```text
PUBLIC RELEASE VERIFICATION PASSED
```

## 3. Bring the production stack up

```bash
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```

Inspect status:

```bash
docker compose --env-file .env -f docker-compose.prod.yml ps
```

The backend readiness check is:

```bash
curl -fsS https://$APP_DOMAIN/api/ready
```

Expected shape:

```json
{"status":"ready","service":"hf-market-engine","market_data_mode":"live"}
```

(`market_data_mode` may be `demo` only when that is intentionally how the public environment is being demonstrated.)

## 4. Public smoke test

Test through Caddy/TLS, not by exposing backend ports:

1. Register/login.
2. Open `/capital`.
3. Confirm provider strip labels reference/assumption/live correctly.
4. Add an owned asset and confirm `/api/assets/summary` changes.
5. Run Capital Evaluate.
6. Open a lane proof drawer.
7. Confirm the receipt graph traverses receipt -> lane -> fact -> source/snapshot.
8. Run Scenario Matrix and confirm owned fleet remains included.
9. Run Optimize and confirm its label exposes `EVIDENCE_BACKED` or `ASSUMPTION_HEAVY`.
10. Confirm there is no execution/spend action from Capital.

## 5. Scale behavior

The public stack is designed for multiple backend workers:

- Mongo stores shared durable state.
- Redis shares request-rate counters across workers.
- Redis gates provider refreshes so each user action does not refetch upstream infrastructure feeds.
- Identical provider payloads reuse content-hashed snapshots.
- Provider raw snapshots larger than the configured safety cap store a hash + truncated preview instead of risking oversized Mongo documents.
- Evidence facts are immutable; new observations supersede rather than overwrite.

Initial provider refresh windows:

- ASIC/hardware feed: 5 minutes.
- GPU compute feed: 2 minutes.
- Energy feed: 1 minute.

These are refresh limits, not claims that the underlying data itself is real-time. The evidence fact's `observed_at`, freshness state, provider, and source remain the truth shown to the user.

## 6. Rollback

The rescue checkpoint from the V2 token cutoff is intentionally preserved separately. For normal production rollback, deploy the last known-good Git commit rather than deleting evidence/state.

Never wipe Mongo evidence collections as a rollback mechanism.

## GitHub Actions note

The repository includes `.github/workflows/verify.yml`. At the time V2 was built, GitHub reported that hosted jobs could not start because the account was locked due to a billing issue. That is an external CI availability failure, not a test pass. Until GitHub Actions can run again, `scripts/verify_public_release.sh` is the executable verification path.
