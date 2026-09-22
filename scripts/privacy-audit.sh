#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EXCLUDES=(
  --exclude-dir=.git
  --exclude-dir=config
  --exclude='privacy-audit.sh'
  --exclude='PRIVACY_AUDIT.md'
  --exclude='*.tar.gz'
  --exclude='*.tgz'
  --exclude='*.zip'
)

# Common fingerprints that should never appear in a public Kyber Core release.
# This is intentionally conservative and is not a replacement for a full secret scanner.
pattern='(dev-disk-by-uuid|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|(^|[^A-Za-z0-9_])(PASSWORD|PASSWD|API_KEY|ACCESS_TOKEN|SECRET_KEY|AUTH_TOKEN)=[^$[:space:]][^[:space:]]*)'

if grep -RInE --binary-files=without-match "${EXCLUDES[@]}" "$pattern" .; then
  echo
  echo "Privacy audit FAILED. Review the matches above before publishing."
  exit 1
fi

echo "Privacy audit PASS. No common private-server patterns were found."
