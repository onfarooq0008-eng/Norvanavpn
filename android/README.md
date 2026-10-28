# Norvane VPN (Android)

One-tap VPN client for the VPNGate backend you deployed. Kotlin, Jetpack Compose, OkHttp.
It asks the backend for a validated OpenVPN profile, hands it to an OpenVPN engine, and shows **Connected only
when the OpenVPN client itself reports an established tunnel**.

> **Status: written but never compiled or run.** The environment that produced this had no Android SDK, Gradle
> or Kotlin compiler. Expect compile fixes, most likely in `IcsOpenVpnEngine.kt`. Nothing here has touched a
> real device, your backend, or a real VPN tunnel.

## About the name
"Norvane" is a coined word. Near-names exist (e.g. Velnex VPN, Velo VPN, VPN Lumos, Hop VPN), so I avoided
those, but I did **not** verify Norvane is free: search the Play Store, trademark databases and domain names
before committing. To rename: `app/src/main/res/values/strings.xml` (`app_name`), `applicationId` in
`app/build.gradle.kts`, the `com.norvane.vpn` package, and the title text in `HomeScreen.kt`.

## Build it
1. Install Android Studio (current stable), open this folder, let it sync. It generates the Gradle wrapper.
   Install the Android SDK platform 35 when prompted.
2. **Backend link** (after you deploy the backend): copy `local.properties.example` to `local.properties`
   and set
   ```
   BACKEND_BASE_URL=https://your-api-domain
   BACKEND_API_KEY=<VPNGATE_APP_API_KEY from /etc/vpngate-backend/env, optional>
   ```
   Must be `https://host[:port]` with no path. Cleartext HTTP is blocked by the network security config.
   Rebuild. Until set, the app shows "Backend not set" and the button is disabled.
3. **OpenVPN engine** (required for real connections):
   ```
   ./scripts/setup-openvpn-engine.sh      # inside a git repo (see ../scripts/init-repo.sh); adds android/ics-openvpn
   ```
   You also need NDK + CMake (SDK Manager) and SWIG (`sudo apt install swig` / `brew install swig`).
   Pin the submodule to a release tag you reviewed. If Gradle complains about flavor dimensions, open
   `ics-openvpn/main/build.gradle` and match the names in `missingDimensionStrategy(...)` in `app/build.gradle.kts`.
   Without the submodule the app builds with a stub engine that reports "engine not installed"; it never fakes a connection.
4. Run on a **real phone** (emulators are unreliable for VpnService). Unit tests: `./gradlew testDebugUnitTest`.

## How it works
`ConnectionManager` (pure Kotlin, covered by 7 unit tests) drives everything:
Requesting -> (VPN permission) -> Connecting -> Connected. Per tap it tries at most 3 servers with 1 s / 2 s backoff
and a 45 s connect timeout per server. Failures go to the backend (`/failure` with a reason) and the next try
sends `exclude=[failed ids]`. Cancel/Disconnect reports `cancelled` (no server penalty) and `/disconnect`.
A dropped tunnel shows "Connection lost" - there is deliberately no silent auto-reconnect.
Profiles are passed in memory to the engine as a temporary profile and are never logged.

## Things to decide / verify before release
- **Licensing:** ics-openvpn is GPL-2.0. Shipping it inside a closed-source app has consequences; get legal advice
  (or use another engine behind the `VpnEngine` interface, which is the only thing the rest of the app touches).
- **Google Play:** VPN apps must use VpnService honestly and complete Play's VPN/permission declarations and
  Data safety form; keep the "volunteer relays, not for anonymity" notice, and do not claim "no logs" or "secure"
  beyond what you can prove. Raise `targetSdk` to the current Play requirement.
- **API key** in the APK is extractable; it is only a speed bump.
- **Real-device test checklist:** consent dialog appears once; Connected appears only after the tunnel is up;
  traffic flows (check your IP); Disconnect works; airplane mode mid-connection shows "Connection lost";
  rotating the screen during connect doesn't hang; backend `vpngate-admin status` shows your reports.
- Unverified guesses: Gradle/AGP/library versions, the ics-openvpn API calls, and the state mapping in
  `IcsOpenVpnEngine.updateState`.
