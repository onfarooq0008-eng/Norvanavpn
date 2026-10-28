# Security notes

## Threat model
VPNGate data and all relays are **untrusted**. A malicious relay operator can observe/alter metadata and
unencrypted traffic and could publish hostile profiles. This backend reduces, but cannot remove, that risk.

## What the backend enforces
- **Profiles**: strict allowlist parser. Rejected: scripts/plugins/`up`/`down`/`tls-verify`, proxies,
  `auth-user-pass`, file references, `route`/`dhcp-option`/`setenv`, `management`, extra blocks, quotes/control
  characters, hostnames (remote must equal the listed public IPv4), multiple remotes, weak ciphers/auth
  (BF/DES/RC*/none, MD4/MD5), compression (default off), missing `<ca>`, oversize (>48 KB).
  Nothing is added, removed or downgraded: valid profiles are re-emitted with certificates untouched.
- **Fetch/SSRF**: only the configured HTTPS URL on an allowlisted host, no redirects, size cap, timeouts,
  retries with backoff. No endpoint takes a URL or command. Probes only target validated public IPv4 addresses.
- **API**: strict pydantic models (unknown fields rejected), regex-validated ids, body size cap (8 KB app + nginx),
  per-address rate limits, constant-time secret comparison, generic error bodies, docs endpoints off.
- **Connection ids**: 192-bit random, hashed at rest, 10-minute life, single terminal report each; failure/success
  reports without a valid id are ignored, so outsiders cannot poison rankings.
- **Privacy**: no access log of client IPs (uvicorn access log off; nginx log format has no address or query).
  Rate-limit counters live in RAM only. Stored telemetry: server id + event kind + timestamp, purged after
  `telemetry_retention_days` (7). No device fingerprinting, no user accounts.
- **Host**: dedicated no-login service user, systemd sandboxing (no new privileges, read-only filesystem except
  the data dir, no capabilities, memory caps), secrets in a root-only 0600 env file (never in config.json or
  logs; log filter redacts secrets, PEM blocks and long blobs), API bound to loopback, UFW allows SSH first.

## Known limits
- `reachable` is a protocol-level reply, not a tunnel test. Real verification must come from a client or you.
- Client reports are unauthenticated beyond holding a valid connection id; a malicious client can trigger a
  cooldown for a server it was issued.
- An API key inside an APK is extractable. Treat it as a speed bump.
- The VPNGate CSV carries client certificates/keys shared by relays; they are passed through as supplied.
- Pinned dependency versions age; review advisories and update `requirements.txt` periodically.
- If you set `allow_insecure_upstream` or `allow_compression`, you accept weaker guarantees.

## Checklist before launch
- [ ] HTTPS works from another machine; HTTP redirects to HTTPS
- [ ] `sudo ufw status` shows SSH allowed and UFW active; port 8000 is **not** open
- [ ] `/etc/vpngate-backend/env` is `-rw------- root root`
- [ ] Admin page needs a password (and ideally an IP allowlist in nginx)
- [ ] Android app waits for the OpenVPN client's CONNECTED state before showing connected
- [ ] You read VPNGate's terms and the licence of your Android OpenVPN library
- [ ] Privacy policy states: relays are volunteer-run, telemetry kept 7 days
- [ ] Backups/monitoring: `systemctl is-active vpngate-api vpngate-worker`, certbot renewal (`systemctl list-timers`)
- [ ] You completed at least one real end-to-end test: tunnel up, traffic flows, disconnect works
