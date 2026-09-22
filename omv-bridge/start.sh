#!/bin/sh
set -eu

export KYBER_BRIDGE_SOCKET="${KYBER_BRIDGE_SOCKET:-/run/kyber-omv/bridge.sock}"

echo "Starting Kyber Core OMV bridge on Unix socket:"
echo "$KYBER_BRIDGE_SOCKET"

exec /usr/bin/python3 /opt/kyber-omv-bridge/bridge.py
