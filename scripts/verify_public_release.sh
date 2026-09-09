#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n==> %s\n' "$*"; }

say "Python syntax (no pyc writes)"
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
import ast
bad = []
for path in Path('backend/app').rglob('*.py'):
    try:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError as exc:
        bad.append(f'{path}:{exc.lineno}: {exc.msg}')
if bad:
    raise SystemExit('\n'.join(bad))
print('ALL BACKEND PYTHON FILES PARSE CLEAN')
PY

say "Backend dependency/import/runtime tests"
(
  cd backend
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
  PYTHONDONTWRITEBYTECODE=1 ENVIRONMENT=development MARKET_DATA_MODE=demo \
    python3 -c "from app.main import app; print(app.title, app.version)"
)

say "Frontend TypeScript"
(
  cd frontend
  npx tsc --noEmit --pretty false
)

say "Frontend production bundle (temp outDir; does not touch root-owned dist)"
TMP_DIST="$(mktemp -d /tmp/hf-market-engine-dist.XXXXXX)"
trap 'rm -rf "$TMP_DIST"' EXIT
(
  cd frontend
  npx vite build --outDir "$TMP_DIST" --emptyOutDir
)

say "Production compose config"
docker compose --env-file .env.example -f docker-compose.prod.yml config >/tmp/hf-market-engine-compose.yml

say "Production images"
docker compose --env-file .env.example -f docker-compose.prod.yml build backend frontend

say "Governance assertions"
python3 - <<'PY'
from pathlib import Path
capital = Path('backend/app/api/capital.py').read_text()
infra = Path('backend/app/core/infrastructure_data.py').read_text()
assets = Path('backend/app/api/infrastructure.py').read_text()
assert 'cannot trade, spend, or deploy' in capital
assert 'OBSERVED_LIVE' in infra and 'USER_ASSUMPTION' in infra
assert '@router.delete' not in assets, 'Asset hard-delete route must not exist'
print('NO EXECUTION CLAIM + NO ASSET HARD DELETE + EVIDENCE STATES PRESENT')
PY

say "PUBLIC RELEASE VERIFICATION PASSED"
