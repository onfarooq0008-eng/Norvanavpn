# VPNGate fastest-server backend

Backend for an Android VPN app. It downloads the public OpenVPN relay list from VPNGate, validates every
profile, probes the best candidates politely, ranks them, and hands your app one validated OpenVPN profile
when the user taps **Connect**.

**Read first (honest limits)**
- VPNGate relays are run by volunteers. Operators can see connection metadata and any unencrypted traffic.
  Do not market this as anonymous or private.
- VPNGate describes its service as an academic project. Check its terms before shipping a public or
  commercial app that depends on it. Nothing here guarantees that any relay works or is the fastest.
- A "reachable" server answered an OpenVPN handshake packet. That is **not** a working tunnel. Only the
  Android client can prove a tunnel; servers become `vpn_verified` only if an operator marks one after a real test.

## What is in the box

```
backend/
  app/            main.py (API factory) serve.py worker.py admin_cli.py config.py
    api/          routes.py errors.py
    services/     vpngate.py (fetch+CSV) profile.py (validator) ranking.py probe.py
                  store.py (SQLite) refresh.py (scheduler) connect.py (logic)
    models/       records.py schemas.py     security/  auth.py ratelimit.py logging_setup.py
  tests/          79 tests (unittest/pytest compatible)
  systemd/        vpngate-api, vpngate-worker, vpngate-healthcheck (service+timer)
  nginx/          site template, http-level snippet, logrotate
  scripts/healthcheck.sh   install.sh   uninstall.sh   requirements.txt   .env.example   config.example.json
  README.md API_DOCUMENTATION.md ANDROID_INTEGRATION.md SECURITY.md
```

Two processes share one SQLite file: `vpngate-api` (FastAPI/uvicorn, loopback only) and `vpngate-worker`
(refresh + probes). nginx terminates HTTPS in front.

## Easiest way (copy and paste)

Upload `vpngate-backend.zip` to your VPS (for example with `scp`, or WinSCP/FileZilla into `/root`), log in over SSH, then paste:

```bash
sudo apt-get update && sudo apt-get install -y unzip
cd ~ && unzip -o vpngate-backend.zip && cd backend
sudo bash quick-start.sh
```

It installs everything, waits for the first server list, runs a plain-English self-test (list, fastest, connect,
disconnect) and prints PASS/FAIL. No website is needed: the backend stays private to the VPS, which is enough to
test it. Re-run the test any time with `sudo bash scripts/selftest.sh`.

**Want the phone app to reach it (needs HTTPS, no website of your own)?** Run:

```bash
sudo bash quick-start.sh --https you@example.com
```

This uses a free address derived from your VPS IP (like `203-0-113-7.sslip.io`) and a free Let's Encrypt
certificate. It needs ports 80 and 443 open in your VPS provider's firewall panel. It prints the two lines to put
in the Android app's `local.properties`. Caveats: that third-party free address and Let's Encrypt limits can fail
or be rate-limited, and this path has not been tested on a live server; for a real launch use your own domain.

## Install (Ubuntu 22.04 / 24.04 VPS)

1. Point a DNS **A record** (e.g. `vpn-api.example.com`) at your VPS. No domain? See "Testing without a domain".
2. Upload this folder (`scp -r backend root@YOUR_VPS:/root/`), then:

```bash
cd /root/backend
sudo ./install.sh --domain vpn-api.example.com --email you@example.com --enable-firewall
```

Without `--enable-firewall` the script adds UFW rules (SSH is always allowed first) but leaves UFW off if it
was off, and tells you. With it, UFW is enabled and every service already listening publicly stays allowed.

The installer checks the OS/CPU/RAM/disk/network, creates the `vpngate` user, venv, config and secrets
(never overwritten on re-run), validates the config, installs systemd units, requests a Let's Encrypt
certificate, starts everything, and tests `/health`. Re-run it any time to update.

### Testing without a domain
The API listens on `127.0.0.1` only. Use an SSH tunnel and test from your computer:
`ssh -L 8000:127.0.0.1:8000 user@YOUR_VPS`, then `curl http://127.0.0.1:8000/health`.
A phone cannot use that tunnel, so for the real app get a domain (a cheap one, or a free subdomain
service). The installer never exposes the API over plain HTTP.

## Check that it works
```bash
curl -s https://vpn-api.example.com/health
curl -s -H "X-API-Key: $(sudo grep APP_API_KEY /etc/vpngate-backend/env | cut -d= -f2)" \
     https://vpn-api.example.com/api/v1/servers/fastest
sudo vpngate-admin status      # counts, last refresh, errors
sudo vpngate-admin top         # best-ranked servers
```
`/health` says `starting` until the first download (usually under a minute), then `ok`; `degraded` means the
list is stale, nothing is eligible, or the worker stopped.

## Operating
| Task | Command |
|---|---|
| Logs | `journalctl -u vpngate-api -u vpngate-worker -f` |
| Restart | `sudo systemctl restart vpngate-api vpngate-worker` |
| Force refresh now | `sudo vpngate-admin refresh` |
| Show secrets | `sudo cat /etc/vpngate-backend/env` |
| Config | `/etc/vpngate-backend/config.json` (see `config.example.json`), then restart |
| Update | upload the new folder, re-run `sudo ./install.sh --domain ... --email ...` |
| Uninstall | `sudo ./uninstall.sh` (asks to confirm; `--keep-data` keeps the database) |

## How ranking works (all weights configurable)
`score = 100 x weighted average` of: advertised speed (log, capped), advertised ping, **latency measured from
your VPS**, session load, uptime, VPNGate score, reliability (EWMA of our probes), freshness (half-life
30 min). Servers sort by tier first (`vpn_verified` > `reachable` > `candidate`) then score. `/connect`
picks randomly among near-equal top servers (top 3 within 8 points, same tier) so one volunteer is not flooded.

Politeness defaults: list refresh every 30 min (minimum enforced 10 min); probes: one packet per server,
at most 20 per 5-minute round, 4 at a time, each server re-probed at most every 15 min, failures cool down
10 min doubling to 6 h. Nothing is probed when a user connects.

## Troubleshooting
- `/health` stays `starting`: `sudo vpngate-admin errors` (upstream unreachable? endpoint changed?).
- Many servers rejected: `sudo vpngate-admin status` prints rejection reasons. Common: `compression_disabled`
  (profiles using `comp-lzo`; set `"allow_compression": true` only if you accept the weaker setting),
  `weak_cipher`, `remote_host_not_ip`.
- `eligible_servers: 0`: all in cooldown or stale; wait for the next probe round or check upstream.
- The upstream endpoint (`https://www.vpngate.net/api/iphone/`) is configurable via `upstream_url`
  (host must also be in `allowed_upstream_hosts`). It was **not** verified live while this was written.
