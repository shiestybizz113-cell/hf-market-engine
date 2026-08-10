# Stripe Test Mode — hf-market-engine

## 1. Create products in Stripe (Test mode)

1. Open [Stripe Dashboard](https://dashboard.stripe.com/test/dashboard) — toggle **Test mode** ON.
2. **Products** → Add product for each plan (recurring monthly):
   - Pro Trader — $59/mo
   - Advanced Trader — $199/mo
   - Team / Community — $699/mo
   - White Label — $1,499/mo (optional setup fee as one-time later)
3. Copy each **Price ID** (`price_...`).

## 2. API keys

Dashboard → Developers → API keys (still in Test mode):

| Env var | Value |
|---------|--------|
| `STRIPE_SECRET_KEY` | `sk_test_...` |
| `STRIPE_PRICE_PRO` | `price_...` |
| `STRIPE_PRICE_ADVANCED` | `price_...` |
| `STRIPE_PRICE_TEAM` | `price_...` |
| `STRIPE_PRICE_WHITELABEL` | `price_...` (optional) |
| `STRIPE_SUCCESS_URL` | `http://localhost:5173/pricing?upgraded=1` |
| `STRIPE_CANCEL_URL` | `http://localhost:5173/pricing?canceled=1` |

Put these in `backend/.env` (never commit real keys).

## 3. Local webhook

```bash
# Install Stripe CLI: https://stripe.com/docs/stripe-cli
stripe login
stripe listen --forward-to localhost:8000/api/billing/webhook
```

CLI prints `whsec_...` → set as `STRIPE_WEBHOOK_SECRET` in `.env`.

## 4. Run stack

```bash
docker compose up --build
# or
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Check: `GET http://localhost:8000/api/billing/status`  
Expect `"stripe_mode": "test"`, `"checkout_ready": true`.

## 5. Test checkout

1. Register / login in the app.
2. Open **Pricing** → **Upgrade** on Pro.
3. Stripe Checkout opens (test mode).
4. Pay with test card: `4242 4242 4242 4242`, any future expiry, any CVC.
5. Webhook fires → user `plan` becomes `pro`.
6. Paper trade / backtest should unlock.

## 6. Without Stripe (gates only)

```bash
curl -X POST http://localhost:8000/api/billing/dev-upgrade \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"pro"}'
```

Disabled when `ENVIRONMENT=production`.

## 7. Go live later

1. Create the same products in **Live** mode.
2. Swap to `sk_live_...` and live `price_...` IDs.
3. Point a real webhook endpoint (HTTPS) to `/api/billing/webhook`.
4. Set `ENVIRONMENT=production`.
