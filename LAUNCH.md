# hf-market-engine — Launch Runbook

> Every launch should be reversible, observable, and incremental.
> This document is the pre-flight checklist and the rollback plan.

**Doctrine:** AI advises. Manda decides. No silent spend. No synthetic live data.

---

## 0. Launch Posture

This deployment ships in **demo mode by default**. Live market data is a
separate, deliberate flip — not part of the initial launch. That flip is
the staged rollout, and it is documented in §5.

| Stage | `MARKET_DATA_MODE` | Who sees it | Risk |
|---|---|---|---|
| Launch | `demo` | Everyone | None — no real capital, no live data |
| Internal | `live` | Founder only, separate instance | Low |
| Beta | `live` | Invited users | Medium |
| GA | `live` | Everyone | Full |

---

## 1. Pre-Launch Checklist

### Code quality
- [x] Backend tests pass (`pytest tests/` — 30 tests)
- [x] Frontend typecheck passes (`tsc --noEmit`)
- [x] Vite build succeeds
- [x] Ruff lint passes
- [x] No `console.log` in frontend source (verified: 0)
- [x] No unresolved `TODO`/`FIXME` (verified: 0)
- [ ] Code reviewed by founder — **REQUIRED before merge to main**

### Security
- [x] No secrets in version control (gitleaks in CI, blocks on detection)
- [x] Rate limiting on auth endpoints (10/min login, 5/min register)
- [x] CORS locked to explicit origins — wildcard rejected in production
- [x] Security headers middleware (CSP, X-Frame-Options, HSTS in prod)
- [x] `SECRET_KEY` length enforced (≥32 chars in production)
- [x] `ARCHISYNAPSE_SIGNING_KEY` required in production (64-char hex)
- [x] MongoDB credentials enforced in production (rejects unauthenticated URL)
- [ ] `npm audit` clean — **run before deploy**
- [ ] Redis configured for rate limits — **see §6 open gaps**

### Infrastructure
- [ ] Production `.env` populated (see §2)
- [ ] `ARCHISYNAPSE_SIGNING_KEY` generated and stored in secrets manager
- [ ] MongoDB reachable with authenticated credentials
- [ ] DNS + SSL configured
- [x] Health check endpoint exists (`/api/health`, `/api/system/health`)
- [ ] Log aggregation configured — **see §6 open gaps**

### Documentation
- [x] `HARNESS.md` current — governance layer documented
- [x] `LAUNCH.md` — this file
- [ ] `README.md` updated with `ARCHISYNAPSE_SIGNING_KEY` setup step

---

## 2. Production Environment

Generate the signing key **once**, then store it in your secrets manager:

```bash
cd backend && python scripts/generate_signing_key.py
```

Required production `.env`:

```bash
ENVIRONMENT=production
SECRET_KEY=<64+ random chars>
ARCHISYNAPSE_SIGNING_KEY=<64-char hex from script above>
MONGODB_URL=mongodb://<user>:<pass>@<host>:27017
MONGODB_DB=hf_market_engine
CORS_ORIGINS=https://your-real-domain.com
MARKET_DATA_MODE=demo
REDIS_URL=redis://<host>:6379

# Governance — spend enforcement + alerting
AI_BUDGET_USER_DAILY_USD=2.00
AI_BUDGET_GLOBAL_DAILY_USD=50.00
AI_BUDGET_ENFORCE=true
ALERT_WEBHOOK_URL=<slack incoming webhook>
```

**The app refuses to boot in production if any of these are missing or weak.**
That is intentional. A boot failure at deploy time is cheaper than a silent
security gap in production.

---

## 3. Deploy Sequence

```
1. Merge to main
   └── CI runs: gitleaks → backend tests → frontend build → integration smoke
   └── Do not proceed if any job is red

2. Deploy to production
   └── docker compose -f docker-compose.prod.yml up --build -d
   └── Watch startup logs for config validation errors

3. Verify (first 10 minutes)
   └── curl https://your-domain/api/health           → 200
   └── curl https://your-domain/api/system/health    → market_data_mode: demo
   └── curl https://your-domain/api/evidence/public-key → stable key, 64 chars
   └── Log in through the UI → DataModeBanner shows amber DEMO MODE
   └── Run one AI analysis → check /api/evidence/receipts shows signature_valid: true

4. Monitor (first hour)
   └── Error logs — no new error types
   └── Auth endpoint 429 rate — should be near zero under normal traffic
   └── Receipt persistence — grep logs for "receipt_persisted: false"
```

---

## 4. Rollback Plan

### Trigger conditions — roll back immediately if:

| Condition | Threshold |
|---|---|
| Error rate | >2x baseline |
| P95 latency | >50% above baseline |
| `receipt_persisted: false` | Any occurrence at meaningful rate |
| Signature verification failures | Any occurrence |
| Demo data appearing in live-mode session | Any occurrence — hard stop |
| Auth 429 spike | >50/hour (signals attack or misconfiguration) |

### Rollback steps

```bash
# 1. Revert the deploy
git revert <commit-sha>
git push origin main
# CI redeploys previous version

# 2. Or immediate: redeploy previous image
docker compose -f docker-compose.prod.yml down
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml up --build -d

# 3. Verify rollback
curl https://your-domain/api/health
curl https://your-domain/api/system/health
```

### Data considerations

- **Receipts are append-only.** A rollback does not delete receipts written
  by the newer version. They remain verifiable against the same signing key.
- **Do not rotate `ARCHISYNAPSE_SIGNING_KEY` during a rollback.** Rotating
  invalidates offline verification of every historical receipt.
- **No destructive migrations exist yet.** MongoDB indexes are created
  idempotently on startup.

### Time to rollback

| Method | Time |
|---|---|
| `MARKET_DATA_MODE=live` → `demo` (env + restart) | < 2 min |
| Redeploy previous version | < 5 min |
| Full stack rebuild | < 10 min |

---

## 5. Staged Rollout — Demo → Live

The riskiest change in this product is not a code deploy. It is the flip
from `MARKET_DATA_MODE=demo` to `live`. Treat it as its own rollout.

```
Stage 1 — Internal (founder only)
  └── Separate instance, MARKET_DATA_MODE=live
  └── Verify: every quote carries a real provider source
  └── Verify: dead provider returns 503, NOT a synthetic number
  └── Verify: DataModeBanner shows green LIVE DATA
  └── 48-hour soak

Stage 2 — Beta (invited users)
  └── Monitor: provider error rates, 503 frequency
  └── Monitor: AI spend per session (see §6 — enforcement not yet built)
  └── 1 week minimum

Stage 3 — GA
  └── Only after Stage 2 shows zero synthetic-data incidents
  └── Verify spend caps sized for real traffic (defaults are conservative)
```

**Kill switch:** Set `MARKET_DATA_MODE=demo` and restart. Under 2 minutes.
The banner flips to amber automatically on the next poll (max 2 min lag),
and immediately on page load.

---

## 6. Open Gaps — Launch Blockers vs. Acceptable

### Blocks live-mode GA

**None.** Both former blockers are closed:

| Former gap | Resolution |
|---|---|
| ~~No AI spend enforcement~~ | `app/core/budget.py` — rolling 24h per-user ($2) and global ($50) caps. Blocks paid inference at cap and returns the rule-based fallback. Fails closed if the ledger is unreadable. Blocked calls still write an auditable receipt. |
| ~~No alert on `receipt_persisted: false`~~ | `app/core/alerting.py` — webhook with per-type dedupe. Fires on receipt write failure, budget breach, and signature failure. Always logs even with no webhook configured. |

Set `ALERT_WEBHOOK_URL` to a Slack incoming webhook before live GA. Log-only
is a valid posture but means you learn about incidents by reading logs.

### Acceptable at demo launch

| Gap | Mitigation |
|---|---|
| Redis not required in dev | In-memory rate limits work single-worker. Set `REDIS_URL` in production. |
| No log aggregation | Docker logs sufficient for initial launch volume. |
| No feature flag system | `MARKET_DATA_MODE` is the only flag that matters right now. |

---

## 7. Post-Launch Verification

Run this within one hour of every deploy:

```bash
BASE=https://your-domain

# Health
curl -sf $BASE/api/health | jq .

# Data mode contract
curl -sf $BASE/api/system/health | jq .market_data_mode
# Expect: "demo"

# Receipt signing is live and stable
curl -sf $BASE/api/evidence/public-key | jq .
# Expect: same public_key across restarts (proves stable signing key)

# Security headers
curl -sI $BASE/api/health | grep -Ei "x-frame|x-content-type|content-security"

# Rate limit enforcement
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code} " \
    -X POST $BASE/api/auth/login \
    -d "username=test@x.com&password=wrong"
done
# Expect: 401s followed by 429s
```

---

## 8. Change Log

| Date | Change | Author |
|---|---|---|
| 2026-08-17 | Initial LAUNCH.md — pre-flight checklist, rollback plan, staged rollout | Claude |
| 2026-08-17 | Security headers middleware (CSP, X-Frame-Options, HSTS) | Claude |
| 2026-08-17 | `ARCHISYNAPSE_SIGNING_KEY` production guard + keygen script | Claude |
| 2026-08-17 | `tests/test_launch.py` — 12 launch-readiness tests | Claude |
| 2026-08-17 | AI spend enforcement + governance alerting — live GA unblocked | Claude |
