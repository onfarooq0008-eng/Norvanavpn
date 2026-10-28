#!/usr/bin/env bash
# VPNGate backend installer - idempotent, safe to re-run (re-running is also how you UPDATE).
# Usage: sudo ./install.sh [--domain api.example.com --email you@example.com] [--port N]
#                          [--enable-firewall] [--no-firewall] [--skip-network-check] [--yes]
set -euo pipefail

APP_USER=vpngate
APP_DIR=/opt/vpngate-backend
DATA_DIR=/var/lib/vpngate-backend
CONF_DIR=/etc/vpngate-backend
ENV_FILE="$CONF_DIR/env"
CONFIG_FILE="$CONF_DIR/config.json"
LOG_DIR=/var/log/vpngate-backend
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/root/vpngate-backup-$TS"

DOMAIN=""; EMAIL=""; PORT=""; YES=0; SKIP_NET=0; NO_FW=0; ENABLE_FW=0
CERT_OK=0

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --skip-network-check) SKIP_NET=1; shift ;;
    --no-firewall) NO_FW=1; shift ;;
    --enable-firewall) ENABLE_FW=1; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

backup() { # backup <file> : copy an existing file we are about to change
  if [ -e "$1" ]; then mkdir -p "$BACKUP_DIR"; cp -a "$1" "$BACKUP_DIR/$(echo "$1" | tr '/' '_')"; fi
}
install_if_changed() { # install_if_changed <src> <dst> <mode>
  if [ -f "$2" ] && cmp -s "$1" "$2"; then return 0; fi
  backup "$2"; install -m "$3" "$1" "$2"
}

# ---------------------------------------------------------------- 1. preflight
[ "${EUID:-$(id -u)}" -eq 0 ] || die "Run as root:  sudo ./install.sh"
[ -d "$SRC_DIR/app" ] && [ -f "$SRC_DIR/requirements.txt" ] || die "Run this from the uploaded project folder (app/ not found next to install.sh)."
[ -r /etc/os-release ] || die "Cannot detect the operating system."
. /etc/os-release
ARCH="$(uname -m)"
say "Detected: ${PRETTY_NAME:-unknown} on $ARCH"
[ "${ID:-}" = "ubuntu" ] || die "This installer supports Ubuntu only (found '${ID:-unknown}')."
case "${VERSION_ID:-}" in
  22.04|24.04|24.10|25.04) ;;
  *) warn "Ubuntu ${VERSION_ID:-?} is not on the tested list (22.04/24.04). Continuing; stop now (Ctrl-C) if unsure." ; sleep 3 ;;
esac
case "$ARCH" in x86_64|aarch64) ;; *) die "Unsupported CPU architecture: $ARCH" ;; esac
command -v systemctl >/dev/null || die "systemd is required."

CPUS="$(nproc)"; MEM_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
DISK_MB="$(df -Pm / | awk 'NR==2 {print $4}')"
say "Resources: ${CPUS} CPU, ${MEM_MB} MB RAM, ${DISK_MB} MB free disk"
[ "$MEM_MB" -ge 400 ] || die "At least ~512 MB RAM is required."
[ "$DISK_MB" -ge 1000 ] || die "At least 1 GB free disk is required."

# Inspect what already runs (informational only; nothing here is modified)
say "Listening sockets (existing services are left untouched):"
ss -H -lntu 2>/dev/null | awk '{print "    " $1, $5}' | sort -u | head -20 || true
if systemctl list-units --type=service --no-legend 2>/dev/null | grep -Eiq 'openvpn|wg-quick|wireguard|strongswan|xl2tpd|softether'; then
  warn "Another VPN service appears to be running on this server. It will NOT be touched."
fi

# Port selection: keep our own existing port; otherwise default 8000 or the next free one.
port_in_use() { ss -H -lnt "sport = :$1" 2>/dev/null | grep -q .; }
if [ -z "$PORT" ]; then
  if [ -f "$CONFIG_FILE" ]; then PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_FILE')).get('bind_port',8000))" 2>/dev/null || echo 8000)"; else PORT=8000; fi
  if ! systemctl is-active --quiet vpngate-api 2>/dev/null; then
    p="$PORT"; while port_in_use "$p" && [ "$p" -lt 8100 ]; do p=$((p+1)); done
    [ "$p" != "$PORT" ] && warn "Port $PORT is busy; using $p instead."
    PORT="$p"
  fi
fi
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || die "Invalid --port"

if [ -n "$DOMAIN" ]; then
  [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || die "Invalid domain name."
  [ -n "$EMAIL" ] || die "--email is required with --domain (used by Let's Encrypt for expiry notices)."
fi

if [ "$SKIP_NET" -eq 0 ]; then
  say "Checking network access..."
  curl -fsS -m 15 -o /dev/null https://www.vpngate.net/en/ || die "Cannot reach https://www.vpngate.net (use --skip-network-check to override)."
  curl -fsS -m 15 -o /dev/null https://pypi.org/simple/pip/ || die "Cannot reach pypi.org (needed to install dependencies)."
fi

# ---------------------------------------------------------------- 2. packages
say "Installing OS packages..."
export DEBIAN_FRONTEND=noninteractive
PKGS="python3 python3-venv python3-pip curl ca-certificates openssl ufw logrotate"
[ -n "$DOMAIN" ] && PKGS="$PKGS nginx certbot python3-certbot-nginx"
apt-get update -qq
# shellcheck disable=SC2086
apt-get install -y -qq $PKGS >/dev/null
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || die "Python 3.10+ is required."

# ---------------------------------------------------------------- 3. account + directories
if ! id "$APP_USER" >/dev/null 2>&1; then
  say "Creating service account '$APP_USER' (no login, no home shell)"
  useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -m 0755 "$APP_DIR" "$APP_DIR/scripts"
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR"
install -d -m 0750 -o root -g "$APP_USER" "$CONF_DIR"
install -d -m 0755 "$LOG_DIR"

# ---------------------------------------------------------------- 4. application files + venv
say "Installing application files..."
rm -rf "$APP_DIR/app"                       # only our own directory is replaced
cp -a "$SRC_DIR/app" "$APP_DIR/app"
find "$APP_DIR/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
install -m 0755 "$SRC_DIR/scripts/healthcheck.sh" "$APP_DIR/scripts/healthcheck.sh"
install -m 0644 "$SRC_DIR/requirements.txt" "$APP_DIR/requirements.txt"
chown -R root:root "$APP_DIR"; chmod -R go-w "$APP_DIR"

if [ ! -x "$APP_DIR/venv/bin/python" ]; then
  say "Creating Python virtual environment..."
  python3 -m venv "$APP_DIR/venv"
fi
say "Installing pinned Python dependencies (this can take a minute)..."
"$APP_DIR/venv/bin/pip" install --quiet --no-cache-dir --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"
"$APP_DIR/venv/bin/pip" freeze > "$APP_DIR/requirements.lock"

# ---------------------------------------------------------------- 5. secrets + config (never overwritten)
if [ ! -f "$ENV_FILE" ]; then
  say "Generating secrets (stored only in $ENV_FILE, mode 0600)"
  umask 077
  { echo "VPNGATE_ADMIN_SECRET=$(openssl rand -hex 32)"
    echo "VPNGATE_APP_API_KEY=$(openssl rand -hex 24)"; } > "$ENV_FILE"
  umask 022
fi
chown root:root "$ENV_FILE"; chmod 0600 "$ENV_FILE"

if [ ! -f "$CONFIG_FILE" ]; then
  say "Writing default config $CONFIG_FILE"
  python3 - "$CONFIG_FILE" "$PORT" <<'PY'
import json, sys
json.dump({"bind_host": "127.0.0.1", "bind_port": int(sys.argv[2])}, open(sys.argv[1], "w"), indent=2)
PY
elif [ -n "$PORT" ]; then
  python3 - "$CONFIG_FILE" "$PORT" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c["bind_port"] = int(sys.argv[2]); json.dump(c, open(sys.argv[1], "w"), indent=2)
PY
fi
chown root:"$APP_USER" "$CONFIG_FILE"; chmod 0640 "$CONFIG_FILE"
PORT="$(python3 -c "import json;print(json.load(open('$CONFIG_FILE')).get('bind_port',8000))")"

# ---------------------------------------------------------------- 6. validate BEFORE enabling anything
say "Validating configuration..."
( set -a; . "$ENV_FILE"; set +a
  cd "$APP_DIR" && PYTHONDONTWRITEBYTECODE=1 VPNGATE_CONFIG="$CONFIG_FILE" "$APP_DIR/venv/bin/python" -c \
    "from app.config import load_config; load_config(); import app.main, app.worker" ) \
  || die "Configuration or application import check failed. Nothing was started."

# ---------------------------------------------------------------- 7. systemd, admin CLI, logrotate
say "Installing systemd units..."
for u in vpngate-api.service vpngate-worker.service vpngate-healthcheck.service vpngate-healthcheck.timer; do
  install_if_changed "$SRC_DIR/systemd/$u" "/etc/systemd/system/$u" 0644
done
if ! out="$(systemd-analyze verify /etc/systemd/system/vpngate-api.service /etc/systemd/system/vpngate-worker.service 2>&1)"; then
  warn "systemd-analyze reported: $out"
fi
cat > /usr/local/bin/vpngate-admin <<'WRAP'
#!/bin/bash
# Admin CLI: sudo vpngate-admin {status|top|errors|refresh|verify ID|unverify ID}
set -euo pipefail
[ "${EUID:-$(id -u)}" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
cd /opt/vpngate-backend
exec runuser -u vpngate -- env VPNGATE_CONFIG=/etc/vpngate-backend/config.json PYTHONDONTWRITEBYTECODE=1 \
  /opt/vpngate-backend/venv/bin/python -m app.admin_cli "$@"
WRAP
chmod 0755 /usr/local/bin/vpngate-admin
install_if_changed "$SRC_DIR/nginx/logrotate-vpngate-backend" /etc/logrotate.d/vpngate-backend 0644

# ---------------------------------------------------------------- 8. nginx + HTTPS (only with a domain)
if [ -n "$DOMAIN" ]; then
  say "Configuring nginx for $DOMAIN"
  install_if_changed "$SRC_DIR/nginx/vpngate-backend-http.conf" /etc/nginx/conf.d/vpngate-backend.conf 0644
  tmp="$(mktemp)"; sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__PORT__/$PORT/g" "$SRC_DIR/nginx/vpngate-backend.conf.template" > "$tmp"
  if [ -f /etc/nginx/sites-available/vpngate-backend ] && grep -q 'listen 443' /etc/nginx/sites-available/vpngate-backend; then
    say "Existing HTTPS site config found; keeping it (certbot-managed)."
  else
    install_if_changed "$tmp" /etc/nginx/sites-available/vpngate-backend 0644
  fi
  rm -f "$tmp"
  ln -sf /etc/nginx/sites-available/vpngate-backend /etc/nginx/sites-enabled/vpngate-backend
  nginx -t || die "nginx configuration test failed; fix it and re-run. (Backups in $BACKUP_DIR)"
  systemctl enable --now nginx >/dev/null 2>&1 || true
  systemctl reload nginx

  PUBIP="$(curl -4 -fsS -m 8 https://api.ipify.org 2>/dev/null || true)"
  DNSIP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}')"
  if [ -z "$DNSIP" ]; then
    warn "$DOMAIN does not resolve yet. Create an A record -> ${PUBIP:-the public IP of this server}, then re-run this installer."
  elif [ -n "$PUBIP" ] && [ "$DNSIP" != "$PUBIP" ]; then
    warn "$DOMAIN resolves to $DNSIP but this server's public IP looks like $PUBIP. Skipping certificate request."
  else
    say "Requesting a Let's Encrypt certificate..."
    if certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --no-eff-email --non-interactive --redirect; then
      CERT_OK=1
    else
      warn "certbot failed. HTTPS is NOT configured. See: journalctl -u nginx, /var/log/letsencrypt/"
    fi
  fi
else
  say "No --domain given: the API stays bound to 127.0.0.1 only (not reachable from the internet)."
fi

# ---------------------------------------------------------------- 9. firewall (SSH is always allowed first)
detect_ssh_ports() {
  { [ -n "${SSH_CONNECTION:-}" ] && echo "$SSH_CONNECTION" | awk '{print $4}'
    ss -H -ltnp 2>/dev/null | awk '/"sshd"/ {n=split($4,a,":"); print a[n]}'
    sshd -T 2>/dev/null | awk '/^port / {print $2}'
  } | grep -E '^[0-9]+$' | sort -un
}
if [ "$NO_FW" -eq 1 ]; then
  warn "Skipping firewall changes (--no-firewall)."
else
  SSH_PORTS="$(detect_ssh_ports || true)"; [ -n "$SSH_PORTS" ] || SSH_PORTS=22
  say "Firewall: allowing SSH on port(s) $(echo $SSH_PORTS | tr '\n' ' ')"
  for p in $SSH_PORTS; do ufw allow "${p}/tcp" >/dev/null; done
  if [ -n "$DOMAIN" ]; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; fi
  if ufw status | grep -q "Status: inactive"; then
    if [ "$ENABLE_FW" -eq 1 ]; then
      # keep every service that is already listening publicly reachable, so enabling cannot break it
      ss -H -lntu 2>/dev/null | awk '$5 !~ /^(127\.|\[::1\]|::1)/ {n=split($5,a,":"); print $1"/"a[n]}' | sort -u | \
        while IFS=/ read -r proto prt; do [[ "$prt" =~ ^[0-9]+$ ]] && ufw allow "$prt/$proto" >/dev/null; done
      ufw --force enable >/dev/null
      say "UFW enabled (SSH + existing public listeners + 80/443 allowed). Review with: ufw status"
    else
      warn "UFW is installed but INACTIVE; rules were added but not enforced. Enable it yourself after checking 'ufw show added':  ufw enable   (or re-run with --enable-firewall)"
    fi
  else
    say "UFW already active; rules added."
  fi
fi

# ---------------------------------------------------------------- 10. start + verify
say "Starting services..."
systemctl daemon-reload
systemctl enable vpngate-api vpngate-worker vpngate-healthcheck.timer >/dev/null 2>&1
systemctl restart vpngate-api vpngate-worker
systemctl start vpngate-healthcheck.timer

HEALTH_URL="http://127.0.0.1:$PORT/health"
ok=0; for _ in $(seq 1 30); do curl -fsS -m 3 "$HEALTH_URL" >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
[ "$ok" -eq 1 ] || { journalctl -u vpngate-api -n 25 --no-pager || true; die "API did not become healthy. See logs above."; }
say "Local API is up: $(curl -fsS -m 3 "$HEALTH_URL")"

say "Waiting up to 2 minutes for the first VPNGate download (status 'starting' -> 'ok')..."
first=0
for _ in $(seq 1 24); do
  if curl -fsS -m 3 "$HEALTH_URL" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('last_refresh_ok') else 1)"; then first=1; break; fi
  sleep 5
done
if [ "$first" -eq 1 ]; then say "First server list downloaded and validated."
else warn "No server list yet. Check:  sudo vpngate-admin errors   and   journalctl -u vpngate-worker -n 50"; fi

BASE="http://127.0.0.1:$PORT"
if [ "$CERT_OK" -eq 1 ]; then
  BASE="https://$DOMAIN"
  if curl -fsS -m 10 "$BASE/health" >/dev/null 2>&1; then say "HTTPS check from this server succeeded."; else warn "HTTPS check from this server failed."; fi
  echo "    (True external reachability must be tested from another machine: curl $BASE/health)"
fi

cat <<DONE

====================================================================
 Installation finished.
 Backend URL ........ $BASE
 Admin page ......... ${DOMAIN:+https://$DOMAIN/admin/  (user: admin)}${DOMAIN:-via SSH tunnel: ssh -L $PORT:127.0.0.1:$PORT user@this-server  then http://127.0.0.1:$PORT/admin/}
 Show secrets ....... sudo cat $ENV_FILE        (admin password + Android API key)
 Status ............. sudo vpngate-admin status | top | errors
 Logs ............... journalctl -u vpngate-api -u vpngate-worker -f
 Restart ............ sudo systemctl restart vpngate-api vpngate-worker
 Update ............. upload the new project folder, then: sudo ./install.sh ${DOMAIN:+--domain $DOMAIN --email $EMAIL}
 Backups of changed files: ${BACKUP_DIR} (only if something was replaced)
$( [ -z "$DOMAIN" ] && echo " HTTPS is NOT configured. Do not expose this API over plain HTTP. Re-run with --domain/--email." )
====================================================================
DONE
