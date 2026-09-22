# Kyber Core 1.0.0

Initial public OpenMediaVault-only release.

## Included

- Kyber Core web dashboard and API
- first-run administrator account creation and login
- OpenMediaVault readiness enforcement
- restricted Unix-socket OMV Compose bridge
- Docker/Compose management features
- LinuxServer/Awesome-Selfhosted app discovery
- container configuration backup and restore
- storage, network, security, audit, update, file, and optional AI tools
- installer and uninstaller
- CI validation and public-release privacy audit

## Deployment note

This application has Docker socket access and should be considered a privileged administrative tool. Keep it on a trusted LAN or behind a properly secured HTTPS reverse proxy. Do not expose it directly to the public Internet.
