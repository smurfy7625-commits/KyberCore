#!/bin/sh
set -eu

REPO_URL="https://github.com/smurfy7625-commits/KyberCore.git"
INSTALL_DIR="${KYBER_INSTALL_DIR:-/opt/kyber-core}"

echo "===== KYBER CORE INSTALLER ====="

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run with sudo or as root."
    exit 1
fi

if [ ! -x /usr/sbin/omv-rpc ]; then
    echo "ERROR: OpenMediaVault was not detected."
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is required."
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: Docker Compose v2 is required."
    exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# If this script was downloaded by itself, fetch the repository so the
# OMV bridge files and Compose file are available.
if [ ! -f "$SCRIPT_DIR/omv-bridge/bridge.py" ] || \
   [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then

    echo "Downloading Kyber Core repository..."

    if ! command -v git >/dev/null 2>&1; then
        apt-get update
        apt-get install -y git
    fi

    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"

    SCRIPT_DIR="$INSTALL_DIR"
fi

echo
echo "===== INSTALL OMV BRIDGE ====="

install -d -m 0755 /opt/kyber-omv-bridge

install -m 0755 \
    "$SCRIPT_DIR/omv-bridge/bridge.py" \
    /opt/kyber-omv-bridge/bridge.py

install -m 0755 \
    "$SCRIPT_DIR/omv-bridge/start.sh" \
    /opt/kyber-omv-bridge/start.sh

install -m 0644 \
    "$SCRIPT_DIR/omv-bridge/kyber-omv-bridge.service" \
    /etc/systemd/system/kyber-omv-bridge.service

systemctl daemon-reload
systemctl enable --now kyber-omv-bridge.service

sleep 2

if [ ! -S /run/kyber-omv/bridge.sock ]; then
    echo "ERROR: OMV bridge socket was not created."
    systemctl --no-pager --full status kyber-omv-bridge.service || true
    journalctl -u kyber-omv-bridge.service -n 80 --no-pager || true
    exit 1
fi

echo "OMV bridge socket ready:"
ls -l /run/kyber-omv/bridge.sock

echo
echo "===== START KYBER CORE ====="

cd "$SCRIPT_DIR"

if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
fi

mkdir -p config

docker compose pull
docker compose up -d

echo
echo "===== VERIFY ====="

docker ps \
    --filter name=kyber-core \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'

echo
echo "Kyber Core installation complete."
echo "Open the host port configured in docker-compose.yml/.env."
