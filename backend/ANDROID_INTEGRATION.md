# Android integration

## 0. Check first
- **WireGuard -> OpenVPN.** VPNGate relays speak OpenVPN, not WireGuard. Your WireGuard tunnel code (and its
  "no handshake" handling) does not apply. You need an OpenVPN client library, `VpnService` permission flow,
  and a foreground service. Remove WireGuard config generation/keys for this path.
- **Licensing.** The common library (*OpenVPN for Android*/ics-openvpn) is GPL-2.0, which has consequences for
  closed-source apps. OpenVPN 3 core is AGPL-3.0 unless you hold a commercial license. Get legal advice
  before shipping; this choice affects your whole app.
- Test code below is an outline, **not compiled or tested**; adapt it to your library's API.

## 1. Flow (never report CONNECTED on HTTP 200)
1. User taps Connect -> state `REQUESTING`. `POST /api/v1/connect` (timeout 10 s). Keep `connection_id`, `server.id`.
2. Ask Android for VPN permission: `VpnService.prepare(context)`; start the activity result if non-null.
3. Hand `openvpn_profile` to the OpenVPN library; state `CONNECTING`. Start a **connect timeout (45 s)**.
4. Listen to the library's connection-state callback. Only when it reports the tunnel is up
   (e.g. `CONNECTED`) set state `CONNECTED` and `POST .../success`.
5. On a terminal failure (auth/TLS failure, `TLS handshake failed`, timeout, process died) stop the tunnel and
   `POST .../failure` with a reason, then retry from step 1 with `exclude=[failed ids]`.
6. Retry policy: at most 3 servers per tap, wait 1 s, 2 s, 4 s between attempts, then show an error. Never
   loop through the list in the background.
7. Disconnect: cancel pending timeouts/requests, stop the tunnel, `POST /api/v1/disconnect`. If a connect was
   in flight, report `failure` with `reason:"cancelled"` (no server penalty).

```kotlin
// Outline only
suspend fun connect(exclude: List<String> = emptyList(), attempt: Int = 1) {
    val r = api.connect(ConnectRequest(exclude = exclude))            // 1
    vpnPermissionGranted()                                            // 2
    val ok = withTimeoutOrNull(45_000) { openVpn.start(r.openvpnProfile).awaitConnected() } // 3-4
    if (ok == true) { state = CONNECTED; api.success(r.server.id, r.connectionId); return }
    openVpn.stop(); api.failure(r.server.id, r.connectionId, "timeout")  // 5
    if (attempt < 3) { delay(1000L shl (attempt - 1)); connect(exclude + r.server.id, attempt + 1) }
    else state = ERROR
}
```

## 2. Security on the app side
- Keep the API key out of source control; accept that it can be extracted from the APK. Pair it with HTTPS and
  the backend's rate limits.
- Do not log the profile or `connection_id`. Do not write the profile to shared storage; pass it in memory.
- Pin nothing weaker than the backend's HTTPS; consider certificate pinning for your own domain.
- Show the `notice` text (volunteer relays, not anonymous) somewhere users can read it.
- Do not edit the profile (no removing `cipher`, no adding scripts). The backend already validated it.

## 3. Diagnosing failures
| Symptom (OpenVPN) | Likely cause | What to do |
|---|---|---|
| Stuck at "waiting for server reply" / `TLS key negotiation failed to occur within 60 seconds` | UDP blocked on the network, relay offline, or a firewall drops it | App retries with another server; try `protocol:"tcp"` |
| `TLS handshake failed` / `certificate verify failed` | Relay certificate not matching the profile CA | Report failure; do **not** disable verification |
| `AUTH_FAILED` | Profile expects credentials | Should not happen (profiles with `auth-user-pass` are rejected) |
| Connects, no internet | Relay has no outbound route or DNS | Report failure; try another |
| Connects then drops quickly | Overloaded volunteer relay | Report failure; cooldown applies |
| `Cipher ... not supported` | Old-style cipher on a modern client | Check client version; server stays out if cipher is weak |

*"No handshake" is WireGuard wording* (no handshake reply from the peer within a few seconds). If you still
see it, you are running the WireGuard path. For OpenVPN the equivalent is the TLS negotiation timeout above.

Backend side: `sudo vpngate-admin status`, `sudo vpngate-admin top`, `journalctl -u vpngate-worker -n 100`,
and a quick check that the server you were given answers: `curl -s https://DOMAIN/api/v1/servers?limit=5`.
