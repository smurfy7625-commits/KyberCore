# Public Release Privacy Audit

Kyber Core v1.0.0 was prepared from a source-only export rather than from the live runtime directory.

The public repository intentionally excludes:

- `.env`
- `config/auth.json`
- runtime settings/audit/history files
- backup archives
- Python cache files
- development backup/checkpoint files
- old project ZIP archives
- private keys, tokens, and credentials
- server-specific disk UUID paths
- private LAN IP addresses
- personal names and location references from the development environment
- legacy Nexus/NexusNAS branding and private helper references

Validation performed for this package:

- Python syntax check for the FastAPI application and OMV bridge
- JavaScript syntax check
- Compose YAML parse check
- shell script syntax check
- scan for common RFC1918 private IP literals
- scan for UUID-style disk identifiers and `dev-disk-by-uuid`
- scan for common embedded secret assignment patterns
- scan for development/personal identifiers used during private development
- scan for legacy Nexus/NexusNAS branding

The included `scripts/privacy-audit.sh` runs a repeatable subset of these checks before future public releases.

No automated scanner can guarantee that a repository contains no sensitive information. Review changes before publishing, especially files added after this release.
