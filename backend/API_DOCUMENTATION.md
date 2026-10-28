# API documentation

Base URL: `https://YOUR_DOMAIN`. All bodies are JSON. If an app key is configured, send `X-API-Key` on
`/api/v1/*`. Errors always look like:

```json
{"success": false, "error": {"code": "rate_limited", "message": "Too many requests."}}
```
Codes: `invalid_request` 400 (adds `fields`), `invalid_server_id` 400, `unauthorized` 401, `not_found` 404,
`unknown_connection` 404, `already_reported` 409, `payload_too_large` 413, `rate_limited` 429 (+`Retry-After`),
`no_server_available` / `inventory_unavailable` 503, `internal_error` 500 (no details leaked).

Example values below come from **test fixtures** (documentation/test addresses and fake certificates), not
from real VPNGate servers.

## GET /health  (no auth)
```json
{"status":"ok","api_uptime_s":812,"last_refresh_ok":"2026-10-25T10:02:11Z","cache_age_s":640,
 "eligible_servers":57,"worker_heartbeat_age_s":9}
```
`status`: `starting` (no download yet), `ok`, `degraded` (stale > 3 h, nothing eligible, or worker silent > 2 min).
Always HTTP 200 while the API process is alive.

## GET /api/v1/servers
Query: `country` (2 letters), `protocol` (`udp|tcp`), `min_quality` (0-100), `limit` (1-100, default 20), `offset`.
```json
{"success":true,"total":2,"limit":20,"offset":0,"servers":[{"id":"be948586d30ea2a1","hostname":"vpn1",
 "ip":"8.8.4.4","country":"Japan","country_code":"JP","protocol":"openvpn","transport":"udp","port":1195,
 "verification_status":"reachable","probe_type":"openvpn_reset","latency_ms":41.7,"quality_score":81.71,
 "advertised_speed_mbps":50.0,"advertised_ping_ms":20,"sessions":10,"last_checked_age_s":10}]}
```
`verification_status`: `candidate` (listed, valid, not recently probed), `reachable` (answered an OpenVPN
handshake packet, or a TCP connect when tls-auth prevents it; see `probe_type`), `vpn_verified` (operator-confirmed
tunnel test). `latency_ms` is `null` for candidates. Advertised speed is not a guarantee.

## GET /api/v1/servers/fastest
Same filters except paging. Deterministic top server: `{"success":true,"server":{...}}`. 503 if none.

## POST /api/v1/connect
Body is optional: `{"protocol":"any|udp|tcp","country":"JP","exclude":["<server id>", ...max 10],"min_quality":0}`.
Use `exclude` to pass servers that already failed in this attempt.
```json
{"success":true,"connection_id":"JwBib7exImwYeKMUY-RIHWZyLbqNprya",
 "server":{"id":"be948586d30ea2a1","hostname":"vpn1","country":"Japan","protocol":"openvpn","transport":"udp",
           "port":1195,"verification_status":"reachable","latency_ms":41.7,"quality_score":81.71, "...":"..."},
 "openvpn_profile":"client\ndev tun\nproto udp\nremote 8.8.4.4 1195\n...<ca>...</ca>\n",
 "expires_at":"2026-10-25T10:12:11Z","notice":"Public VPNGate relays are run by volunteers..."}
```
The profile is always inline: profiles larger than `max_profile_bytes` (48 KB) are rejected during refresh, so
no separate download endpoint is needed. `connection_id` is random (192 bits), stored only as a SHA-256 hash,
valid `connection_ttl_s` (10 min), and required for reports. Do not log the profile or the id.

## POST /api/v1/servers/{server_id}/failure
`{"connection_id":"...","reason":"timeout|auth|tls|no_handshake|network|cancelled|other"}` ->
`{"success":true,"recorded":true}`. Starts a cooldown (10 min, doubling per consecutive failure, max 6 h).
`reason:"cancelled"` (user pressed Disconnect) records no penalty. One report per connection id (second -> 409).
The id in the URL must be the server issued for that connection, else 404.

## POST /api/v1/servers/{server_id}/success
`{"connection_id":"..."}`. Counts as an **untrusted client signal**; it never makes a server `reachable` or
`vpn_verified`. Send it only after the OpenVPN client reports the tunnel as established.

## POST /api/v1/disconnect
`{"connection_id":"..."}` -> `{"success":true}`. Idempotent; deletes the short-lived connection record.

## GET /api/v1/stats
`{"success":true,"stats":{"candidates":2,"reachable":1,"vpn_verified":0,"eligible":2,"in_cooldown":0,
"recent_failures_24h":0,"last_refresh_ok_ts":1000.0,"cache_age_s":10,"inventory_stale":false,
"worker_heartbeat_age_s":9}}`

## Admin (HTTP Basic, user `admin`, password = `VPNGATE_ADMIN_SECRET`; disabled if no secret is set)
`GET /admin/` HTML status page - `GET /admin/api/status` JSON - `POST /admin/refresh` - 
`POST /admin/servers/{id}/verified` with `{"verified":true}` after you personally confirmed a working tunnel
(expires after 7 days). Failed attempts are rate limited. Consider restricting `/admin/` by IP in nginx.
There is no endpoint that runs commands or fetches arbitrary URLs. `/docs` and `/openapi.json` are disabled
(`enable_docs` turns them on).

## Rate limits (per client address, in memory only)
connect 10/min, reports 30/min, reads 60/min, admin 10/min; nginx adds 10 req/s. Configurable.
