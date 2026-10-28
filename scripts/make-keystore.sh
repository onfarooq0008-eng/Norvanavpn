#!/usr/bin/env bash
# Creates your release signing key and the values for the GitHub secrets. Run it on YOUR computer, once.
# Usage: bash scripts/make-keystore.sh [output-folder]      (default: ~/norvane-keystore)
set -euo pipefail
OUT="${1:-$HOME/norvane-keystore}"
JKS="$OUT/norvane-release.jks"
die() { echo "[problem] $*" >&2; exit 1; }
command -v keytool >/dev/null || die "keytool not found. Install a JDK 17 (it comes with Android Studio: <Studio>/jbr/bin)."
command -v openssl >/dev/null || die "openssl not found."
[ ! -e "$JKS" ] || die "$JKS already exists. Refusing to overwrite your signing key."
mkdir -p "$OUT"; chmod 700 "$OUT"

PASS="$(openssl rand -hex 16)"       # 32 random hex characters
ALIAS="norvane"
DNAME="${KEY_DNAME:-CN=Norvane VPN}"
keytool -genkeypair -keystore "$JKS" -alias "$ALIAS" -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "$PASS" -keypass "$PASS" -dname "$DNAME" >/dev/null 2>&1 || die "keytool failed."
chmod 600 "$JKS"

B64="$(base64 < "$JKS" | tr -d '\n')"
SECRETS="$OUT/secrets.txt"
umask 077
{
  echo "Add these as GitHub repository SECRETS (Settings > Secrets and variables > Actions > New repository secret):"
  echo
  echo "KEYSTORE_PASSWORD=$PASS"
  echo "KEY_PASSWORD=$PASS"
  echo "KEY_ALIAS=$ALIAS"
  echo "KEYSTORE_BASE64=$B64"
} > "$SECRETS"

echo "Created:"
echo "  $JKS       <- your signing key. BACK IT UP (password manager / offline copy). Never commit it."
echo "  $SECRETS   <- the 4 secret values to paste into GitHub. Delete it after you pasted them."
echo
echo "Certificate fingerprint (to compare with the CI log later):"
keytool -list -keystore "$JKS" -storepass "$PASS" 2>/dev/null | grep -i "fingerprint" || true
