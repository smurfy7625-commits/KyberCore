# Kyber Core

Kyber Core is a self-hosted **OpenMediaVault homelab command center** for Docker and the OpenMediaVault Compose plugin. It provides a single web interface for system status, containers, Compose projects, storage, networking, app discovery, configuration-only container backups, updates, security visibility, audit logs, and optional local-AI diagnostics.

> **Platform scope:** this release is intentionally OpenMediaVault-only. Kyber Core requires OpenMediaVault, the OMV Compose plugin, Docker, and the included local Unix-socket OMV bridge.

## Highlights

- First-run administrator account creation; no default credentials
- Login-required dashboard and protected API routes
- PBKDF2-SHA256 password hashing and HttpOnly session cookies
- OpenMediaVault readiness check before account creation
- Docker container inventory, actions, logs, inspection, and resource statistics
- Compose project discovery, validation, editing, deployment, pull/restart/down operations
- LinuxServer.io installable catalog plus Awesome-Selfhosted discovery catalog
- OMV Compose registration through a root-owned Unix-domain socket bridge
- Storage, SMART, network, listeners, Docker networks, security visibility, and audit history
- **Container Backups**: Compose/YAML/env plus mapped configuration directories only
- Pre-restore safety backup and controlled configuration restore
- Optional Ollama-powered diagnostics
- Environment-based configuration with no server-specific values committed to Git

## Important backup scope

Kyber Core's **Container Backups** are configuration backups. They do **not** back up media libraries, downloads, arbitrary storage, or the entire OpenMediaVault server. Use a separate storage/backup strategy for important data.

## Requirements

- OpenMediaVault with the Compose plugin installed and working
- Docker and Docker Compose
- Root/sudo access during installation of the OMV bridge
- A trusted local network

Kyber Core mounts `/var/run/docker.sock`, so the application has powerful Docker-level administrative access. Treat it as a privileged management tool.

## Installation

Clone or download this repository onto your OpenMediaVault server, then run:

```bash
cd kyber-core
sudo ./install.sh
```

The installer:

1. Verifies OpenMediaVault, `omv-rpc`, Docker, and Docker Compose.
2. Installs the restricted OMV bridge under `/opt/kyber-omv-bridge`.
3. Installs and enables `kyber-omv-bridge.service`.
4. Creates `.env` from `.env.example` if needed.
5. Prompts for the host Compose and storage roots.
6. Builds and starts Kyber Core.
7. Checks both the OMV bridge and Kyber Core.

When installation completes, open:

```text
http://YOUR-OMV-SERVER:8088
```

On first launch, Kyber Core shows **Create Administrator Account**. Choose your own credentials; there are no defaults.

## Manual configuration

Copy the example file and edit values before starting:

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

Key settings:

```dotenv
CONTAINER_NAME=kyber-core
KYBER_PORT=8088
TZ=UTC
PUID=1000
PGID=100
HOST_COMPOSE_ROOT=/opt/compose
HOST_STORAGE_ROOT=/srv
OLLAMA_URL=
OLLAMA_MODEL=qwen3:4b
AUTH_SESSION_SECONDS=43200
AUTH_COOKIE_SECURE=false
```

`HOST_COMPOSE_ROOT` must point to the host directory containing the Compose projects Kyber Core should manage. `HOST_STORAGE_ROOT` controls the storage tree visible to Kyber Core.

For plain local HTTP, leave `AUTH_COOKIE_SECURE=false`. If Kyber Core is served through HTTPS, set it to `true`.

## Authentication and account recovery

The administrator record is stored in `config/auth.json`. Passwords are not stored in plaintext. Sessions are held in memory, so a Kyber Core restart signs users out without deleting the administrator account.

If the administrator password is lost, from the repository directory on the OMV host:

```bash
docker compose down
mv config/auth.json config/auth.json.locked-out-backup
docker compose up -d
```

Then open Kyber Core and create a new administrator account. Protect the backup file because it contains the password hash and salt.

## OMV bridge

The included bridge exposes only a small API over `/run/kyber-omv/bridge.sock` for the operations Kyber Core currently needs. The socket is root-owned and mode `0600`.

The bridge supports:

- health/readiness check
- OMV Compose file listing
- OMV Compose project registration
- OMV Compose project deletion

It is not a general-purpose command execution service and is not exposed on a TCP port.

## Updating

From the repository directory:

```bash
git pull
docker compose up -d --build
sudo systemctl restart kyber-omv-bridge.service
```

Run `./scripts/privacy-audit.sh` before publishing your own fork or release.

## Uninstalling

```bash
sudo ./uninstall.sh
```

By default the uninstall script stops/removes the Kyber Core container and OMV bridge but preserves the local `config/` directory. It does not remove unrelated Docker containers, Compose projects, media, downloads, or general storage.

## Security

- Keep Kyber Core on a trusted LAN or behind an appropriately configured HTTPS reverse proxy.
- Do not expose the application directly to the public Internet.
- Docker socket access is effectively host-administrative access.
- The OMV bridge intentionally uses a local Unix socket rather than a network listener.
- Never commit `.env`, `config/auth.json`, runtime JSON/JSONL data, backups, access tokens, or private keys.
- Review [SECURITY.md](SECURITY.md) before deployment.

## Optional local AI

Set `OLLAMA_URL` to an Ollama-compatible local endpoint and choose `OLLAMA_MODEL`. The AI feature is intended for diagnostics and evidence-based recommendations; it does not silently apply repairs.

## Privacy of this public repository

This release contains no intentional server IP addresses, disk UUIDs, hostnames, account credentials, auth database, access tokens, server-specific Compose directories, or user backup archives. A repository privacy audit script and CI check are included to help prevent accidental publication later.

## License

MIT. See [LICENSE](LICENSE).
