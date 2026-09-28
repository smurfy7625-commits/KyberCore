# Updating Kyber Core

## Recommended update

Run from the directory containing Kyber Core's `docker-compose.yml`:

```bash
docker compose pull
docker compose up -d
```

Then verify:

```bash
docker compose ps
docker logs --tail 100 kyber-core
curl -fsS http://127.0.0.1:${KYBER_PORT:-8089}/api/auth/status
```

You can also run:

```bash
bash scripts/verify-install.sh
```

## Why Kyber updates last

Kyber Core may be orchestrating updates for other containers. If it stops itself in the middle of that workflow, the update process can end before Kyber is started again.

Use this order:

1. update ordinary containers
2. exclude `kyber-core` from bulk stop/remove/recreate operations
3. update Kyber Core last from the OpenMediaVault host
4. verify `/api/auth/status`

## Persistent authentication files

Keep these on the persistent `/app/config` volume:

- `auth.json`
- `auth_session_secret`

Deleting them may require account/session setup again.

## Never publish runtime secrets

Do not commit `.env`, authentication files, backups, logs, caches, tokens, private IP addresses, disk UUIDs, or machine-specific storage paths.
