# hf-market-engine — Governance Harness

> "A working loop and a safe loop are not the same thing,
>  and the gap between them is where real incidents happen."

This document is the outer-loop governance layer for hf-market-engine.
It defines who can stop a loop, what conditions trigger a stop, and what
evidence is required before any loop runs unsupervised.

**Doctrine:** AI advises. Manda decides. No silent spend. No synthetic live data.

---

## 1. Data Mode Contract

| Env var value | Behavior | UI indicator |
|---|---|---|
| `MARKET_DATA_MODE=demo` | DemoProvider only. All quotes labeled `source=demo`. | Amber banner — non-dismissable |
| `MARKET_DATA_MODE=live` | Real providers only. Missing data stays missing (503, no synthetic fill). | Green indicator — always visible |

**Non-negotiable:** No automatic fallback from live to demo. A dead live
provider returns a gap, not a fabricated number. The UI banner enforces this
at every view — it re-polls the backend every 2 minutes.

**Who can change mode:** Founder-level `.env` edit + server restart only.
No runtime toggle. No API endpoint. This is deliberate.

---

## 2. Auth Rate Limits (Outer-Loop Kill Switch)

Implemented via `slowapi` middleware. Fail-closed: if the limiter cannot
determine state, it denies.

| Endpoint | Limit | Rationale |
|---|---|---|
| `POST /api/auth/login` | 10 req / min / IP | Brute-force floor |
| `POST /api/auth/register` | 5 req / min / IP | DB write cost + signup abuse |

Returns `HTTP 429` with `Retry-After` header. Never silently swallowed.

**Redis:** When `REDIS_URL` is set, limits are shared across workers and
survive restarts. Required in production. Dev uses in-process memory.

**Raising limits:** Edit `LOGIN_LIMIT` / `REGISTER_LIMIT` in
`backend/app/core/rate_limit.py`. Document the reason and date in this file.

| Date | Change | Reason | Approved by |
|---|---|---|---|
| — | Initial limits (10/5 per min) | Phase 1 baseline | Manda |

---

## 3. Evidence Receipt Chain

Every AI analysis call persists an `analysis_receipt` to MongoDB with:

- `user_id` — who triggered it
- `job` — what the analysis was
- `input_snapshot` — the market state at call time
- `model` / `provider` — which AI backend
- `estimated_cost` — token cost estimate
- `fallback` / `simulation` flags
- `generated_at` — UTC timestamp, immutable after write

**No receipt = no analysis.** If the DB write fails, the analysis result
is still returned but flagged `receipt_persisted: false`. This is the
only acceptable gap and must be monitored.

**Archisynapse v1.1 integration target:** ✅ Phase 2 complete. Raw MongoDB writes replaced with Ed25519-signed receipts via `app.core.archisynapse`. Every receipt carries `input_hash`, `output_hash`, `signature`, and `public_key` for offline tamper verification. Set `ARCHISYNAPSE_SIGNING_KEY` in production `.env`.

---

## 4. Loop Kill Conditions

These are the conditions under which any automated loop MUST stop,
regardless of whether it is "working correctly."

### Spend — ENFORCED
- Per-user 24h AI spend exceeds **$2.00** → block paid inference, return fallback, alert (`AI_BUDGET_USER_DAILY_USD`)
- Global 24h AI spend exceeds **$50.00** → block all paid inference, alert (`AI_BUDGET_GLOBAL_DAILY_USD`)
- Spend ledger unreadable → **fail closed**, block rather than bill blind
- Auth endpoint returns 429 more than **50 times / hour** → alert (monitoring only)

Spend is computed from the signed receipt ledger — the same append-only record
an auditor reads. Enforcement and evidence cannot disagree, because they are
the same data. Blocked calls still write a receipt with `provider=budget_blocked`,
so the block itself is auditable.

### Data integrity
- `MARKET_DATA_MODE=live` but no live provider responds → return 503, do not synthesize
- AI analysis output contains no `receipt_id` → flag `receipt_persisted: false`, alert
- Any quote with `source=demo` appears in a live-mode session → hard stop

### Auth loop
- More than **3 consecutive 401s** from the same token → invalidate token, require re-login
- Login rate limit hit → enforce 60-second backoff before next attempt

---

## 5. Monitoring Checklist (Dashboards ≠ Enforcement)

The distinction that matters:

| Type | Example | Enforces? |
|---|---|---|
| Observability | Seeing spend on a dashboard | ❌ No |
| Enforcement | Rate limiter returning 429 | ✅ Yes |
| Enforcement | Banner blocking unsurfaced demo data | ✅ Yes |
| Enforcement | 503 instead of synthetic fill in live mode | ✅ Yes |
| Enforcement | Budget gate blocking paid inference at cap | ✅ Yes |
| Enforcement | Fail-closed on unreadable spend ledger | ✅ Yes |
| Observability | Alert webhook on receipt write failure | ❌ No (but no longer silent) |

**Phase 1 enforcement gaps (known, tracked):**

- [x] ~~No spend enforcement on AI token cost per session~~ — `app/core/budget.py`: rolling 24h caps (per-user + global), fail-closed, blocks paid inference and returns fallback
- [ ] No Redis-backed rate limiting in dev — in-memory only, resets on restart
- [x] ~~No automated alert on `receipt_persisted: false`~~ — `app/core/alerting.py`: webhook + dedupe, fires on receipt write failure, budget breach, signature failure
- [x] ~~No CI/CD pipeline~~ — `.github/workflows/ci.yml` wired: secret scan → backend tests → frontend typecheck → integration smoke

These gaps are not acceptable in production. Each requires a PR before
investor demo mode.

---

## 6. CI/CD Gate (Phase 1 Target)

No code reaches `main` without passing:

```
1. Backend: pytest backend/tests/ (target: >80% coverage on core/ and api/)
2. Frontend: tsc --noEmit (zero TypeScript errors)
3. Frontend: ESLint (zero errors)
4. Integration: smoke-test.sh against docker-compose stack
5. Security: no hardcoded secrets (gitleaks or equivalent)
```

Until CI is wired:
- All changes reviewed by founder before merge
- `scripts/smoke-test.sh` run manually before any deploy
- No deploy on Fridays (standard)

---

## 7. Outer-Loop Ownership

| Layer | Owner | Kill authority |
|---|---|---|
| Data mode | Manda (env var) | Full — no API override |
| Rate limits | Manda (config edit) | Full — per-endpoint |
| AI spend | Budget gate (automatic) + Manda (key revocation) | Automatic at cap; nuclear via key revocation |
| Evidence receipts | Archisynapse (Phase 2) | Audit trail only |
| Deploy | Manda (CI/CD, Phase 1 manual) | Full |

**No loop runs unsupervised until all Phase 1 enforcement gaps above are closed.**

---

## 8. Change Log

| Date | Change | Author |
|---|---|---|
| 2026-08-17 | Initial HARNESS.md — Phase 1 governance layer | Claude / Manda |
| 2026-08-17 | DataModeBanner component — demo/live surfaced every view | Claude |
| 2026-08-17 | Auth rate limiting — slowapi, 10/5 per min, fail-closed | Claude |
| 2026-08-17 | CI/CD pipeline — secret scan → backend tests → frontend typecheck → smoke | Claude |
| 2026-08-17 | Archisynapse v1.1 — Ed25519 signed receipts, tamper verification, /evidence API upgrade | Claude |
| 2026-08-17 | Security headers + ARCHISYNAPSE_SIGNING_KEY production guard | Claude |
| 2026-08-17 | AI spend enforcement — per-user + global 24h caps, fail-closed | Claude |
| 2026-08-17 | Governance alerting — webhook on receipt failure, budget breach, tampering | Claude |
