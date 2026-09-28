#!/usr/bin/env bash
set -u

KYBER_CONTAINER="${CONTAINER_NAME:-kyber-core}"
PORT="${KYBER_PORT:-8089}"
failures=0

ok()   { printf '[OK]   %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*"; failures=$((failures + 1)); }

command -v docker >/dev/null 2>&1 && ok "Docker command is available" || bad "Docker command is missing"

if docker ps --format '{{.Names}}' 2>/dev/null | grep -Fxq "$KYBER_CONTAINER"; then
  ok "Kyber Core container is running"
else
  bad "Kyber Core container is not running"
fi

if docker inspect "$KYBER_CONTAINER" >/dev/null 2>&1; then
  if docker exec "$KYBER_CONTAINER" test -S /run/kyber-omv/bridge.sock 2>/dev/null; then
    ok "OMV bridge socket exists"
  else
    bad "OMV bridge socket is missing"
  fi

  if docker exec "$KYBER_CONTAINER" test -f /app/config/auth.json 2>/dev/null; then
    ok "Persistent auth.json exists"
  else
    warn "auth.json not found; this can be normal before first-run account creation"
  fi

  if docker exec "$KYBER_CONTAINER" test -f /app/config/auth_session_secret 2>/dev/null; then
    ok "Persistent auth_session_secret exists"
  else
    bad "auth_session_secret is missing"
  fi
fi

if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/api/auth/status" >/dev/null 2>&1; then
  ok "/api/auth/status is responding"
else
  bad "/api/auth/status is not responding on port ${PORT}"
fi

if [[ "$failures" -eq 0 ]]; then
  printf '\nKyber Core verification passed.\n'
  exit 0
fi

printf '\nKyber Core verification found %s failure(s).\n' "$failures"
exit 1
