# Changelog

## 1.0.1 - 2026-09-28

### Fixed

- Fixed administrator sessions being lost after a Kyber Core container restart.
- Added persistent signed session handling backed by `/app/config/auth_session_secret`.
- Preserved administrator account data in `/app/config/auth.json`.
- Fixed first-run authentication persistence and login throttling behavior.
- Fixed update logic that could stop Kyber Core during an automated update and leave it offline.
- Added self-protection guidance so Kyber Core is excluded from generic bulk stop/remove/recreate operations.
- Improved update detection/cache refresh behavior and Kyber Core container/image identification.
- Improved GPU status handling when NVIDIA tooling is unavailable inside the container.
- Fixed Seerr open/integration handling.
- Fixed application-store ordering and several startup/UI issues.

### Added

- Stage 1 per-container configuration backup and restore support.
- Pre-restore safety backups.
- Protection against backing up large media/general-storage paths as container configuration.
- Configurable startup splash behavior and startup validation checks.
- Safe host-side Kyber update helper.
- Installation verification helper.
- Public update and bug-fix documentation.

### Security

- Administrator passwords use PBKDF2-SHA256 with a random salt and 600,000 iterations.
- Session cookies are HttpOnly.
- Session lifetime is configurable with `AUTH_SESSION_SECONDS`.
- Public-repository guidance excludes `.env`, authentication files, backups, logs, caches, private IPs, disk UUIDs, credentials, and host-specific paths.

## 1.0.0

- Kyber Core OpenMediaVault-only public release
- First-run administrator account creation and login protection
- OpenMediaVault readiness requirement
- Unix-socket OMV Compose bridge
- Docker and Compose management dashboard
- App discovery and LinuxServer installer workflow
- Container configuration backup and restore with pre-restore safety backup
- Storage, network, security, audit, updates, file management, and optional local-AI diagnostics
- Public-release privacy audit and CI validation
