#!/usr/bin/env bash
# Plain-English self-test of the running backend. Safe to run any time.
set -u
CONF=/etc/vpngate-backend/config.json
ENVF=/etc/vpngate-backend/env
PORT=$(python3 -c "import json;print(json.load(open('$CONF')).get('bind_port',8000))" 2>/dev/null || echo 8000)
BASE="${SELFTEST_BASE_URL:-http://127.0.0.1:$PORT}"
KEY="${SELFTEST_API_KEY:-$(grep -s '^VPNGATE_APP_API_KEY=' "$ENVF" | cut -d= -f2-)}"
WAIT_TRIES="${SELFTEST_WAIT_TRIES:-36}"
HDR=(); [ -n "$KEY" ] && HDR=(-H "X-API-Key: $KEY")
PASS=0; FAIL=0
ok()  { printf '  [ OK ] %s\n' "$*"; PASS=$((PASS+1)); }
bad() { printf '  [FAIL] %s\n' "$*"; FAIL=$((FAIL+1)); }
jget() { python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for k in sys.argv[1].split('.'):
        d = d[int(k)] if isinstance(d, list) else d[k]
    print(d)
except Exception:
    print('')" "$1"; }

echo "Testing the backend at $BASE"
echo "1) Is the service running, and has it downloaded the VPNGate list?"
status=""
for i in $(seq 1 "$WAIT_TRIES"); do
  h=$(curl -fsS -m 5 "$BASE/health" 2>/dev/null || true)
  status=$(printf '%s' "$h" | jget status)
  [ "$status" = "ok" ] && break
  [ "$i" = 1 ] && echo "     waiting (up to 3 minutes) for the first server list..."
  sleep 5
done
case "$status" in
  ok) ok "service is healthy ($(printf '%s' "$h" | jget eligible_servers) usable servers)";;
  degraded) bad "service runs but is 'degraded' (no usable servers yet). Look at:  sudo vpngate-admin errors";;
  starting) bad "service is up but has not downloaded the server list. Look at:  sudo vpngate-admin errors";;
  *) bad "service did not answer. Look at:  sudo journalctl -u vpngate-api -n 30 --no-pager";;
esac

if [ "$status" = "ok" ] || [ "$status" = "degraded" ]; then
  echo "2) Can the app list servers?"
  total=$(curl -fsS -m 10 "${HDR[@]}" "$BASE/api/v1/servers?limit=3" 2>/dev/null | jget total)
  if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then ok "$total servers available"; else bad "no servers returned (wrong API key, or list empty)"; fi

  echo "3) Can the app ask for the fastest server?"
  f=$(curl -fsS -m 10 "${HDR[@]}" "$BASE/api/v1/servers/fastest" 2>/dev/null)
  c=$(printf '%s' "$f" | jget server.country)
  if [ -n "$c" ]; then ok "fastest server is in: $c (status: $(printf '%s' "$f" | jget server.verification_status))"; else bad "no fastest server returned"; fi

  echo "4) Does 'Connect' hand out a valid OpenVPN profile?"
  r=$(curl -fsS -m 10 "${HDR[@]}" -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/api/v1/connect" 2>/dev/null)
  cid=$(printf '%s' "$r" | jget connection_id)
  prof=$(printf '%s' "$r" | jget openvpn_profile); prof="${prof:0:6}"
  if [ -n "$cid" ] && [ "$prof" = "client" ]; then ok "got a profile for a server in $(printf '%s' "$r" | jget server.country)"; else bad "connect failed (response: $(printf '%s' "$r" | head -c 150))"; fi

  echo "5) Does 'Disconnect' work?"
  if [ -n "$cid" ]; then
    d=$(curl -fsS -m 10 "${HDR[@]}" -X POST -H 'Content-Type: application/json' -d "{\"connection_id\":\"$cid\"}" "$BASE/api/v1/disconnect" 2>/dev/null | jget success)
    [ "$d" = "True" ] && ok "disconnect accepted" || bad "disconnect failed"
  else bad "skipped (no connection was created)"; fi
fi

echo
echo "Result: $PASS passed, $FAIL failed."
echo "Note: this tests the BACKEND only. It cannot prove a real VPN tunnel works; that needs the Android app."
[ "$FAIL" -eq 0 ]
