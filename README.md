# Norvane VPN - full project

```
backend/   VPNGate relay backend (Python/FastAPI) + installer for your Ubuntu VPS
android/   Norvane VPN Android app (Kotlin/Compose)
.github/workflows/ci.yml   GitHub Actions: tests + debug APK on every push, signed AAB on tags
docs/      GITFLOW.md (branches + releases), SIGNING.md (keys + secrets)
scripts/   init-repo.sh (git setup), make-keystore.sh (signing key)
```

## Honest status
Everything was written without a compiler for the Android side and without a live server. Never run end to end:
the GitHub workflow, the Gradle build, the OpenVPN engine integration, and the real VPNGate download.
Tested here: backend unit tests (79; the REST ones will run for the first time in CI), the backend scripts against
a fake server, YAML validity of the workflow, and the keystore and repo-setup scripts. **Expect to fix a few
errors on the first CI run**, most likely in `android/.../IcsOpenVpnEngine.kt` and Gradle versions.

## Quick path (about 20 minutes)
1. **Backend on your VPS:** see `backend/README.md` ("Easiest way"): `sudo bash quick-start.sh`, or with `--https you@mail.com` for the phone app.
2. **Make it a git repo** (on your computer, needs git + internet):
   ```bash
   bash scripts/init-repo.sh
   ```
3. **Push to a new PRIVATE GitHub repository** (commands are printed by the script).
4. **Open the Actions tab.** The first run builds the debug APK: download `norvane-debug-apk` from the run's Artifacts.
5. **Signed AAB:** follow `docs/SIGNING.md` (make the key, add 4 secrets + 1 variable), then
   `git tag v0.1.0 && git push origin v0.1.0` and download `norvane-release-aab`.

## Things only you can decide or check
- App name availability (Norvane is a coined name I did not verify), trademark, Play Store listing.
- **Licensing:** the engine (ics-openvpn) is GPL-2.0, which affects closed-source apps. Get advice before releasing.
- **VPNGate terms** and Google Play's VPN policy / declarations; do not promise anonymity.
- A **real-phone test** with a real tunnel is the only proof that connecting works.
- A debug APK without the engine submodule installs but cannot connect (the CI summary warns you).
