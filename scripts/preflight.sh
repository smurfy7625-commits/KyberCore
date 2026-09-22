#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m py_compile app/main.py omv-bridge/bridge.py
python3 - <<'PY'
import pathlib, yaml
with open('docker-compose.yml', encoding='utf-8') as f:
    data=yaml.safe_load(f)
assert isinstance(data, dict) and 'services' in data
assert 'kyber-core' in data['services']
print('Compose YAML: OK')
PY

if command -v node >/dev/null 2>&1; then
  node --check app/static/app.js
  echo "JavaScript: OK"
fi

./scripts/privacy-audit.sh

echo "Preflight PASS"
