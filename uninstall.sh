#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this uninstaller with sudo or as root."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "This removes the Kyber Core container and OMV bridge."
echo "The repository config/ directory is preserved."
read -r -p "Continue? [y/N]: " answer
case "$answer" in
  y|Y|yes|YES) ;;
  *) echo "Cancelled."; exit 0 ;;
esac

docker compose down || true
systemctl disable --now kyber-omv-bridge.service || true
rm -f /etc/systemd/system/kyber-omv-bridge.service
rm -rf /opt/kyber-omv-bridge
rm -f /run/kyber-omv/bridge.sock
systemctl daemon-reload

echo "Kyber Core was removed. Local config/ was preserved."
