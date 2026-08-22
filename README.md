# hf-market-engine

**Capital + Compute Intelligence Infrastructure** for deciding where capital, power, and compute should go.

The flagship surface is the **Capital Allocation Command Center**: one evidence-backed operating frame across BTC treasury, Bitcoin mining, AI/GPU compute, energy/storage, and the operator's existing fleet.

> **Evidence before recommendation.**  
> Research • Simulation • Capital Allocation • Risk • Proof  
> **Not financial advice. The Capital optimizer proposes only and cannot trade, spend, or deploy capital.**

## What the product does

### Capital Allocation Command Center

Compare the next dollar and next megawatt across:

- BTC treasury
- Bitcoin mining
- AI / GPU compute
- Energy / storage
- Cash / reserve inside the allocation proposal

Every run exposes:

- deterministic economics
- scenario matrix / stress cases
- evidence quality by lane
- live vs assumption percentages
- stale / conflicting / missing facts
- owned-asset baseline
- AI Capital Council explanation
- immutable receipt + proof graph

### Evidence fabric

Capital inputs follow this path:

```text
PROVIDER / OPERATOR INPUT
        ↓
IMMUTABLE EVIDENCE FACT
        ↓
NORMALIZED CAPITAL STATE
        ↓
DETERMINISTIC ECONOMICS
        ↓
SCENARIO / OPTIMIZER
        ↓
AI EXPLANATION
        ↓
CAPITAL RECEIPT
        ↓
PROOF GRAPH
```

Evidence states are explicit:

- `OBSERVED_LIVE`
- `USER_ASSUMPTION`
- `SIMULATION`
- `UNAVAILABLE`

Data quality is surfaced as:

- `COMPLETE`
- `PARTIAL`
- `STALE`
- `CONFLICTING`
- `UNAVAILABLE`

Missing or stale data is never silently replaced with synthetic live data.

## Infrastructure intelligence

### Bitcoin mining

- live/demo network provider separation
- ASIC economics
- Mine-vs-Buy
- fleet modeling
- difficulty / BTC / power scenarios
- user-input provenance
- evidence receipts

### AI / GPU compute

- GPU capex + power economics
- build-vs-cloud frame
- normalized provider offers by region / billing model
- utilization / uptime / PUE assumptions
- evidence-backed comparison to mining and treasury

### Energy / storage

- wholesale / tariff / contract / operator-cost separation
- energy sale / avoided-cost economics
- storage economics with verified MWh ↔ kWh units
- owned storage excluded from new-purchase capex
- regional provider context without pretending wholesale equals delivered electricity cost

### Customer asset registry

Operators can register existing:

- ASIC fleets
- GPU fleets
- power capacity
- storage
- BTC / cash treasury

Assets are retired rather than hard-deleted. Changes emit new evidence instead of rewriting history.

## Market + trading research surfaces

The earlier market stack remains part of the product:

- crypto / stocks / ETFs / macro research
- signal engine
- strategy builder / backtesting
- paper trading
- portfolio / P&L
- risk engine
- execution simulation
- journal

These feed the broader capital-intelligence system; they are not the top-level product definition anymore.

## Provider honesty contract

`MARKET_DATA_MODE=demo`

- demo providers only
- simulation clearly labeled

`MARKET_DATA_MODE=live`

- real providers only
- missing data stays missing
- no automatic demo fallback

Capital V2 also supports optional canonical feeds for:

- ASIC / hardware offers
- GPU compute offers
- energy prices

When these are not configured, reference values remain assumptions rather than being called live.

## Production architecture

- Frontend: React + TypeScript + Vite + nginx
- Backend: FastAPI / Uvicorn
- Durable state: MongoDB
- Shared public rate limits + provider refresh gates: Redis
- Edge / TLS: Caddy
- Deployment: Docker Compose production stack

```text
PUBLIC HTTPS
     ↓
   CADDY
   ↙   ↘
 SPA   /api
       ↓
   FASTAPI WORKERS
      ↙    ↘
   MONGO   REDIS
      ↑
EVIDENCE / ASSETS / RECEIPTS
```

Only Caddy exposes public ports in the production Compose stack.

## Verify a public release

```bash
bash scripts/verify_public_release.sh
```

The release is not considered verified unless that ends with:

```text
PUBLIC RELEASE VERIFICATION PASSED
```

The script runs:

- Python AST/syntax validation without writing `__pycache__`
- Capital V2 backend integrity tests
- FastAPI import check
- TypeScript check
- Vite production build to a temporary output directory
- production Compose validation
- production backend/frontend container builds
- governance assertions for no Capital execution + no asset hard-delete route

## Public deployment

See [`docs/PUBLIC_DEPLOYMENT.md`](docs/PUBLIC_DEPLOYMENT.md).

Production entrypoint:

```bash
cp .env.example .env
# fill domain / secrets / provider configuration
bash scripts/verify_public_release.sh
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```

Readiness:

```bash
curl -fsS https://$APP_DOMAIN/api/ready
```

## Pricing currently encoded in the product

| Plan | Price |
|---|---:|
| Free | $0/mo |
| Pro Trader | $59/mo |
| Advanced | $199/mo |
| Team | $699/mo |
| White Label | $5,000 setup + $1,499/mo |

Do not market capabilities that are not actually enabled for the selected plan/runtime.

## Safety / scope

This platform provides research, simulation, and AI-assisted capital intelligence. It is not financial advice and does not guarantee profits. Trading, mining, infrastructure investment, energy projects, and digital assets involve substantial financial and operating risk.
