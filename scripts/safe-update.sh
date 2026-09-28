#!/usr/bin/env bash
set -Eeuo pipefail

KYBER_CONTAINER="${CONTAINER_NAME:-kyber-core}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
PORT="${KYBER_PORT:-8089}"

log() { printf '[kyber-update] %s\n' "$*"; }
fail() { printf '[kyber-update] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker command not found"
docker compose version >/dev/null 2>&1 || fail "docker compose is unavailable"
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"

log "Validating Compose file..."
docker compose -f "$COMPOSE_FILE" config >/dev/null

log "Pulling the latest Kyber Core image..."
docker compose -f "$COMPOSE_FILE" pull kyber-core

log "Starting/recreating Kyber Core..."
docker compose -f "$COMPOSE_FILE" up -d kyber-core

log "Waiting for Kyber Core..."
for _ in $(seq 1 60); do
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$KYBER_CONTAINER" 2>/dev/null || true)"

  case "$state" in
    healthy|running)
      if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/api/auth/status" >/dev/null 2>&1; then
        log "Kyber Core is online and responding."
        docker compose -f "$COMPOSE_FILE" ps kyber-core
        exit 0
      fi
      ;;
    unhealthy|exited|dead)
      docker logs --tail 100 "$KYBER_CONTAINER" || true
      fail "Kyber Core entered state: $state"
      ;;
  esac

  sleep 2
done

docker logs --tail 100 "$KYBER_CONTAINER" || true
fail "Timed out waiting for Kyber Core"
