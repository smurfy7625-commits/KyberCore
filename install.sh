#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this installer with sudo or as root."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "== Kyber Core OpenMediaVault installer =="

for cmd in python3 docker systemctl omv-rpc; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd"
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose plugin is required."
  exit 1
fi

if ! omv-rpc -u admin Compose getFileList '{"start":0,"limit":1,"sortfield":"name","sortdir":"ASC"}' >/dev/null 2>&1; then
  echo "ERROR: OpenMediaVault Compose RPC is unavailable."
  echo "Install/enable the OMV Compose plugin before Kyber Core."
  exit 1
fi

install -d -m 0755 /opt/kyber-omv-bridge
install -m 0755 omv-bridge/bridge.py /opt/kyber-omv-bridge/bridge.py
install -m 0755 omv-bridge/start.sh /opt/kyber-omv-bridge/start.sh
install -m 0644 omv-bridge/kyber-omv-bridge.service /etc/systemd/system/kyber-omv-bridge.service

systemctl daemon-reload
systemctl enable --now kyber-omv-bridge.service

if [[ ! -S /run/kyber-omv/bridge.sock ]]; then
  echo "ERROR: OMV bridge socket was not created."
  systemctl status kyber-omv-bridge.service --no-pager || true
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env

  DEFAULT_COMPOSE="/opt/compose"
  [[ -d /Compose ]] && DEFAULT_COMPOSE="/Compose"

  read -r -p "Host Compose root [$DEFAULT_COMPOSE]: " HOST_COMPOSE_INPUT || true
  HOST_COMPOSE_INPUT="${HOST_COMPOSE_INPUT:-$DEFAULT_COMPOSE}"

  read -r -p "Host storage root [/srv]: " HOST_STORAGE_INPUT || true
  HOST_STORAGE_INPUT="${HOST_STORAGE_INPUT:-/srv}"

  python3 - "$HOST_COMPOSE_INPUT" "$HOST_STORAGE_INPUT" <<'PY'
from pathlib import Path
import sys
p=Path('.env')
s=p.read_text()
s=s.replace('HOST_COMPOSE_ROOT=/opt/compose', f'HOST_COMPOSE_ROOT={sys.argv[1]}')
s=s.replace('HOST_STORAGE_ROOT=/srv', f'HOST_STORAGE_ROOT={sys.argv[2]}')
p.write_text(s)
PY

  chmod 0600 .env
fi

mkdir -p config
chmod 0700 config

docker compose up -d --build

PORT="$(awk -F= '/^KYBER_PORT=/{print $2}' .env | tail -1)"
PORT="${PORT:-8088}"

for _ in $(seq 1 30); do
  if python3 - "$PORT" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(f'http://127.0.0.1:{sys.argv[1]}/api/auth/status', timeout=2).read()
PY
  then
    echo
    echo "Kyber Core is running."
    echo "Open: http://YOUR-OMV-SERVER:${PORT}"
    echo "Create the administrator account on first launch."
    exit 0
  fi
  sleep 2
done

echo "ERROR: Kyber Core did not become ready in time."
docker compose ps || true
docker compose logs --tail=100 kyber-core || true
exit 1
