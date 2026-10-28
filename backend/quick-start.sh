#!/usr/bin/env bash
# One-command setup + test for beginners.
#   sudo bash quick-start.sh                      -> install, test on the VPS itself (no website needed)
#   sudo bash quick-start.sh --https you@mail.com -> also get free HTTPS on a free address (for the phone app)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

EMAIL=""; IP=""; DRY=0; HTTPS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --https) HTTPS=1; EMAIL="${2:-}"; shift 2 || { echo "Usage: --https your@email.com"; exit 1; } ;;
    --ip) IP="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[problem]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$DRY" -eq 1 ] || [ "${EUID:-$(id -u)}" -eq 0 ] || die "Please run it with sudo, like:  sudo bash quick-start.sh"
[ -f install.sh ] && [ -d app ] || die "Run this from inside the 'backend' folder (the one containing install.sh)."
chmod +x install.sh uninstall.sh scripts/*.sh 2>/dev/null || true

if [ "$HTTPS" -eq 1 ]; then
  [[ "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "Give a real email: sudo bash quick-start.sh --https you@example.com"
  if [ -z "$IP" ]; then
    IP="$(curl -4 -fsS -m 8 https://api.ipify.org 2>/dev/null || curl -4 -fsS -m 8 https://ifconfig.me 2>/dev/null || true)"
  fi
  [[ "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "Could not detect this server's public IP. Re-run with:  --ip YOUR.VPS.IP"
  HOST="${IP//./-}.sslip.io"   # free public DNS name that points at the IP (sslip.io); no website needed
  CMD=(./install.sh --domain "$HOST" --email "$EMAIL" --yes)
  BASE_URL="https://$HOST"
else
  CMD=(./install.sh --no-firewall --yes)
  BASE_URL=""
fi

if [ "$DRY" -eq 1 ]; then echo "Would run: ${CMD[*]}"; echo "Backend URL would be: ${BASE_URL:-none (local test only)}"; exit 0; fi

say "Installing (about 2-5 minutes). You can ignore the long text; it prints a summary at the end."
"${CMD[@]}" || die "The installer stopped. Copy the last 20 lines above and send them to me."

say "Testing the backend on this server..."
TEST_OK=0
./scripts/selftest.sh && TEST_OK=1 || true

KEY="$(grep -s '^VPNGATE_APP_API_KEY=' /etc/vpngate-backend/env | cut -d= -f2- || true)"
echo
echo "=============================================================="
if [ "$TEST_OK" -eq 1 ]; then echo " SUCCESS: the backend works on your VPS."; else echo " The backend installed but some tests failed (see [FAIL] above)."; fi
if [ -n "$BASE_URL" ]; then
  if curl -fsS -m 10 "$BASE_URL/health" >/dev/null 2>&1; then echo " HTTPS address works from this server:  $BASE_URL"
  else echo " HTTPS address could not be reached from this server yet: $BASE_URL"
       echo " Check that ports 80 and 443 are open in your VPS provider's firewall panel, then run this script again."; fi
  echo
  echo " For the Android app, put these two lines in local.properties:"
  echo "   BACKEND_BASE_URL=$BASE_URL"
  echo "   BACKEND_API_KEY=$KEY"
else
  echo " Backend is private to this VPS (not reachable from the internet), which is fine for testing."
  echo " Test again any time:  sudo bash scripts/selftest.sh"
  echo " The phone app needs HTTPS. When ready:  sudo bash quick-start.sh --https you@example.com"
fi
echo " See servers:  sudo vpngate-admin top      Logs:  sudo journalctl -u vpngate-worker -n 30 --no-pager"
echo "=============================================================="
