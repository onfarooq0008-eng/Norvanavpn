# Signing the release AAB

Google Play only accepts a **signed** app bundle (`.aab`). The signing key lives on your computer; GitHub only
gets an encrypted copy as a *secret*, used for the release build and removed from the build machine afterwards.

## 1. Create the key (once, on your computer)
```bash
bash scripts/make-keystore.sh
```
Needs `keytool` (included with a JDK / Android Studio). It creates, in `~/norvane-keystore/`:
- `norvane-release.jks` - the key. **Back it up now** (password manager or offline drive). Never commit or send it.
- `secrets.txt` - four values for GitHub. Delete this file after step 2.

Recommended: enroll in **Play App Signing** when you create the app in Play Console. Then this key is only an
"upload key" and Google can reset it if you ever lose it. Without Play App Signing, losing the key means you can
never update your app.

## 2. Add the secrets and variable in GitHub
Repository > **Settings > Secrets and variables > Actions**

**Secrets** tab > *New repository secret* (one each, names must match exactly):

| Name | Value from `secrets.txt` |
|---|---|
| `KEYSTORE_BASE64` | the long text after `KEYSTORE_BASE64=` |
| `KEYSTORE_PASSWORD` | after `KEYSTORE_PASSWORD=` |
| `KEY_ALIAS` | `norvane` |
| `KEY_PASSWORD` | after `KEY_PASSWORD=` |
| `BACKEND_API_KEY` | (optional) value of `VPNGATE_APP_API_KEY` on your server: `sudo grep APP_API_KEY /etc/vpngate-backend/env` |

**Variables** tab > *New repository variable*:

| Name | Value |
|---|---|
| `BACKEND_BASE_URL` | `https://your-api-address` (https, no trailing path). The release build refuses to run without it. |

## 3. Build
Tag a release (`git tag v0.1.0 && git push origin v0.1.0`) or run the workflow by hand (see GITFLOW.md).
The job fails early with a clear message if a secret is missing. After building it verifies the bundle is signed
and prints the certificate fingerprint; it fails if the bundle carries the debug certificate. Compare that
fingerprint with the one `make-keystore.sh` printed.

## Local release build (optional)
```bash
export KEYSTORE_PATH=$HOME/norvane-keystore/norvane-release.jks
export KEYSTORE_PASSWORD=...   KEY_ALIAS=norvane   KEY_PASSWORD=...
cd android && gradle :app:bundleRelease        # (or ./gradlew after running `gradle wrapper` once)
```

## Security notes
- Secrets are not exposed to pull requests from forks. Keep the repository private.
- The API key is compiled into the app and can be extracted from the APK/AAB; treat it as a deterrent only.
- If the key leaks: remove the secrets, and (with Play App Signing) ask Google to reset your upload key.
