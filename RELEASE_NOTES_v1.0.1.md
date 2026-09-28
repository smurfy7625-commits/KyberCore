# Kyber Core v1.0.1

Release date: September 28, 2026

This release focuses on authentication persistence, safer self-updates, backup reliability, and stability fixes.

## Persistent login sessions

Kyber Core now uses a persistent session signing secret at:

`/app/config/auth_session_secret`

The administrator account remains stored at:

`/app/config/auth.json`

Both are preserved by the existing `./config:/app/config` volume.

## Safer self-updates

Kyber Core should not stop/remove itself in the middle of a bulk container update. Update ordinary containers first, then update Kyber Core last from the OpenMediaVault host.

Recommended Kyber update:

```bash
docker compose pull
docker compose up -d
```

See `docs/UPDATING.md` and `scripts/safe-update.sh`.

## Container Backups - Stage 1

Stage 1 includes per-container configuration backups, mapped `/config` data, pre-restore safety backups, and protection against unintentionally copying media/general-storage trees into configuration backups.

## Other fixes

- update-cache/update-status handling
- Kyber container/image identification
- GPU status fallback behavior
- Seerr open/integration handling
- application-store ordering
- startup splash/check/failsafe behavior
- authentication throttling and first-run persistence

## Security

Do not commit `.env`, `config/auth.json`, `config/auth_session_secret`, backups, logs, caches, credentials, private IP addresses, host disk UUIDs, or other machine-specific values.
