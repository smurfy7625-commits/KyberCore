KYBER CORE ONE-COMMAND INSTALL FILES

Add these files to the KyberCore GitHub repository:

omv-bridge/bridge.py
omv-bridge/start.sh
omv-bridge/kyber-omv-bridge.service
install.sh

The installer:
1. Verifies OpenMediaVault and Docker.
2. Installs and starts the host-side OMV bridge.
3. Verifies /run/kyber-omv/bridge.sock.
4. Pulls the GHCR Kyber Core image using docker compose.
5. Starts Kyber Core.

Recommended public command after committing these files:

curl -fsSL https://raw.githubusercontent.com/smurfy7625-commits/KyberCore/main/install.sh | sudo sh

Important:
Your repository must also contain docker-compose.yml and .env.example.
The GHCR image must already be published and public.
