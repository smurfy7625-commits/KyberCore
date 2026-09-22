# Contributing

Contributions are welcome.

Before opening a pull request:

```bash
./scripts/preflight.sh
```

Do not commit real `.env` files, credentials, tokens, `config/auth.json`, runtime data, private IP addresses, disk UUIDs, server hostnames, backup archives, or server-specific paths.

Keep OpenMediaVault-specific behavior explicit. This release intentionally targets OpenMediaVault rather than generic Docker hosts.
