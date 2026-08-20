# Rollback Plan — Execution Impact Model (`sqrt_law_v1`)

**Change:** Execution cost figures move from `random.uniform()` draws to a
square-root impact model. Five fabricated fields are removed or replaced.

**Classification:** Data-integrity migration, not a feature launch. Displayed
cost numbers will change for every paper order. That is the intent.

---

## Why the normal rollout thresholds do not apply

The shipping checklist compares a canary against a baseline. Here the baseline
is a random number generator, so error-rate and latency comparisons are not the
relevant signal — the change is expected to alter output, and agreement with
the previous values would indicate the patch had failed.

Watch these instead:

| Signal | Expected | Investigate if |
|---|---|---|
| Fill prices | Change vs. previous runs | Identical to pre-patch values |
| `max_slice_impact_bps` | Null, or a measured number | Values in the old 2–9 bps band |
| `vwap_benchmark` | Null | Non-null |
| `participation_rate_realized` | Null | Non-null |
| Repeat identical order | Identical cost both times | Costs differ |
| Thin-liquidity asset | Materially higher impact bps | Same as a liquid asset |

---

## Trigger conditions

Roll back if:

- Impact estimates are non-deterministic for identical inputs
- Fill prices move in the wrong direction relative to side
- Impact figures are implausible by orders of magnitude (e.g. >1000 bps on a
  liquid asset at low participation)
- Any frontend surface renders a null impact field as `0` rather than as
  unavailable

Do **not** roll back merely because reported costs increased. Higher costs
against a random baseline are the expected outcome.

---

## Rollback steps

**Primary — under one minute, no deploy:**

```bash
IMPACT_MODEL=none
```

Restart. Impact fields report null; no fabricated numbers are reintroduced.

**Do not** roll back to `IMPACT_MODEL=legacy_random` in production. `config.py`
refuses to start with that value in production, deliberately: it reports
randomly generated figures as if they were execution costs. It remains
available in development for debugging comparisons only.

**Secondary — full revert:**

```bash
git revert <commit> && git push
```

## Database considerations

No migration. No schema change. `ExecutionAnalytics` fields affected were
already `Optional`. Orders written before the patch retain their stored values
and are not rewritten — historical records keep whatever numbers they were
created with, which means **pre-patch orders still contain fabricated cost
figures.** They should not be cited as evidence.

## Time to rollback

| Path | Duration |
|---|---|
| `IMPACT_MODEL=none` | < 1 min |
| Full git revert | < 5 min |
| Database | N/A |

---

## Post-deploy verification

1. `GET /api/health` returns 200
2. Submit an identical paper order twice; confirm costs match exactly
3. Submit against a thin-liquidity asset; confirm impact bps is materially
   higher than for a liquid one
4. Confirm `vwap_benchmark` and `participation_rate_realized` render as
   unavailable in the UI, not as `0`
5. Confirm production refuses to boot with `IMPACT_MODEL=legacy_random`

## Known limitations at ship time

- `Y = 0.6` is the literature midpoint and has **not** been calibrated against
  this system's fills. All estimates carry
  `evidence_state = ESTIMATED_UNCALIBRATED`. Do not present them as a cost
  commitment.
- The crossover participation (0.001) was chosen from equity literature and may
  be miscalibrated for crypto venue depth.
- `volume_24h` is used as an ADV proxy.
- Impact is schedule-independent by construction, so it cannot distinguish
  TWAP from VWAP from POV. Do not use it to rank execution algorithms.
- No transient decay: this is peak impact, not the post-replenishment residual.

## Still open — not addressed by this change

These remain red on the pre-launch checklist and are not closed by shipping
the impact model:

- No CI. Nothing runs these tests automatically on push.
- No auth rate limiting.
- No error reporting or monitoring configured.
