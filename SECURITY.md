# Security Policy

Kyber Core is a privileged OpenMediaVault administration application. It mounts the Docker socket and can manage files under configured host roots.

## Deployment guidance

- Run Kyber Core only on a trusted network or behind an HTTPS reverse proxy with appropriate access controls.
- Do not expose Kyber Core directly to the public Internet.
- Keep OpenMediaVault, Docker, the Compose plugin, and the host OS patched.
- Protect `.env`, `config/auth.json`, backup archives, and audit/runtime files.
- Set `AUTH_COOKIE_SECURE=true` when Kyber Core is accessed exclusively through HTTPS.
- Restrict filesystem permissions on the repository and `config/` directory.

## OMV bridge

The OMV bridge listens only on a Unix-domain socket at `/run/kyber-omv/bridge.sock`. It intentionally implements a small allow-listed set of OMV Compose operations instead of exposing arbitrary shell execution.

## Reporting a vulnerability

Do not post credentials, private IP addresses, disk UUIDs, logs containing secrets, or exploit details from a live server in a public issue. Use the repository owner's private security-reporting channel if one is enabled on GitHub.
