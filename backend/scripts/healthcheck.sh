#!/usr/bin/env bash
# Restarts the API if /health does not answer, and the worker if its heartbeat is stale.
set -u
CONF=/etc/vpngate-backend/config.json
PORT=$(python3 -c "import json;print(json.load(open('$CONF')).get('bind_port',8000))" 2>/dev/null || echo 8000)
URL="http://127.0.0.1:${PORT}/health"
body=$(curl -fsS --max-time 5 "$URL" 2>/dev/null) || { sleep 5; body=$(curl -fsS --max-time 5 "$URL" 2>/dev/null); } || true
if [ -z "${body:-}" ]; then
  logger -t vpngate-healthcheck "API did not answer on $URL; restarting vpngate-api"
  systemctl restart vpngate-api
  exit 0
fi
age=$(printf '%s' "$body" | python3 -c "import sys,json;v=json.load(sys.stdin).get('worker_heartbeat_age_s');print('' if v is None else int(v))" 2>/dev/null || true)
if [ -n "$age" ] && [ "$age" -gt 600 ]; then
  logger -t vpngate-healthcheck "worker heartbeat is ${age}s old; restarting vpngate-worker"
  systemctl restart vpngate-worker
fi
exit 0
