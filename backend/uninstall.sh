#!/usr/bin/env bash
# Removes ONLY this project's services and files. Usage: sudo ./uninstall.sh [--yes] [--keep-data] [--remove-user]
set -euo pipefail
YES=0; KEEP_DATA=0; RM_USER=0
for a in "$@"; do case "$a" in --yes|-y) YES=1;; --keep-data) KEEP_DATA=1;; --remove-user) RM_USER=1;; *) echo "unknown option $a"; exit 1;; esac; done
[ "${EUID:-$(id -u)}" -eq 0 ] || { echo "Run as root: sudo ./uninstall.sh" >&2; exit 1; }

cat <<LIST
This will remove:
  systemd units  vpngate-api, vpngate-worker, vpngate-healthcheck (service+timer)
  /opt/vpngate-backend, /etc/vpngate-backend (config + secrets), /var/log/vpngate-backend
  /usr/local/bin/vpngate-admin, /etc/logrotate.d/vpngate-backend
  nginx site 'vpngate-backend' and /etc/nginx/conf.d/vpngate-backend.conf (if present)
$( [ "$KEEP_DATA" -eq 1 ] && echo "  (database /var/lib/vpngate-backend is KEPT)" || echo "  /var/lib/vpngate-backend (database)" )
It will NOT remove: installed apt packages, firewall rules, TLS certificates, other services.
LIST
if [ "$YES" -ne 1 ]; then
  read -r -p "Type 'yes' to confirm: " confirm
  [ "$confirm" = "yes" ] || { echo "Aborted."; exit 1; }
fi

for u in vpngate-healthcheck.timer vpngate-healthcheck.service vpngate-api.service vpngate-worker.service; do
  systemctl disable --now "$u" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$u"
done
systemctl daemon-reload
rm -f /etc/nginx/sites-enabled/vpngate-backend /etc/nginx/sites-available/vpngate-backend /etc/nginx/conf.d/vpngate-backend.conf
if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then systemctl reload nginx 2>/dev/null || true; fi
rm -rf /opt/vpngate-backend /etc/vpngate-backend /var/log/vpngate-backend
[ "$KEEP_DATA" -eq 1 ] || rm -rf /var/lib/vpngate-backend
rm -f /usr/local/bin/vpngate-admin /etc/logrotate.d/vpngate-backend
if [ "$RM_USER" -eq 1 ] && id vpngate >/dev/null 2>&1; then userdel vpngate || true; fi
echo "Removed. Leftovers you may want to review manually:"
echo "  - firewall rules:  ufw status numbered"
echo "  - TLS certificate: certbot certificates   (delete with: certbot delete --cert-name YOUR_DOMAIN)"
