#!/usr/bin/env bash
# Quick smoke test for hf-market-engine (requires backend running on :8000)
set -e
BASE="${BASE_URL:-http://localhost:8000}"

echo "== Health =="
curl -sf "$BASE/api/health" | head -c 200
echo ""

echo "== System health =="
curl -sf "$BASE/api/system/health" | head -c 300
echo ""

echo "== Pricing plans =="
curl -sf "$BASE/api/pricing/plans" | head -c 200
echo ""

echo "== Execution algos catalog =="
curl -sf "$BASE/api/execution/algos" | head -c 200
echo ""

echo "== Market overview (CoinGecko) =="
curl -sf "$BASE/api/market/overview" | head -c 300
echo ""

echo "== Register test user =="
EMAIL="smoke_$(date +%s)@test.local"
curl -sf -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"smokeTest1!\",\"full_name\":\"Smoke\"}" | head -c 200
echo ""

echo "== Login =="
TOKEN=$(curl -sf -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$EMAIL&password=smokeTest1!" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token acquired: ${TOKEN:0:20}..."

echo "== Me =="
curl -sf "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN" | head -c 200
echo ""

echo "== Signals =="
curl -sf "$BASE/api/market/signals?limit=2" -H "Authorization: Bearer $TOKEN" | head -c 200
echo ""

echo "SMOKE OK"
echo "Docker: docker compose up --build"
echo "Backend only: cd backend && uvicorn app.main:app --reload"
echo "Frontend: cd frontend && npm i && npm run dev"
