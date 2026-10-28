# Branching and releases (git-flow, simplified)

| Branch | Purpose | CI result |
|---|---|---|
| `main` | Only released, working code | tests + debug APK |
| `develop` | Daily integration branch | tests + debug APK |
| `feature/<name>` | One change; branch from `develop`, merge back via pull request | tests + debug APK |
| `release/<x.y.z>` | Final polish before a release | tests + debug APK |
| `hotfix/<name>` | Urgent fix; branch from `main`, merge into `main` and `develop` | tests + debug APK |
| tag `vX.Y.Z` | A release | tests + debug APK **+ signed release AAB** |

## Everyday
```bash
git checkout develop && git pull
git checkout -b feature/server-list
# ...edit, then:
git add -A && git commit -m "Add server list screen" && git push -u origin feature/server-list
# open a Pull Request into develop on GitHub; merge when CI is green
```

## Making a release
```bash
git checkout main && git merge --no-ff develop      # (or merge a release/x.y.z branch)
git tag v0.1.0 && git push origin main v0.1.0
```
Pushing the tag starts the release build. Open the **Actions** tab, open the run, and download
`norvane-release-aab` from **Artifacts** at the bottom. The tag number becomes the app version (`0.1.0`);
the build counter becomes the `versionCode` (it only ever goes up, which Google Play requires).
Then merge `main` back into `develop`.

Manual build without a tag: Actions > CI > **Run workflow**, tick "Also build the signed release AAB".

## Where do the files come from?
- Debug APK: Actions run > Artifacts > `norvane-debug-apk` (kept 14 days). It is signed with the standard debug key.
  Install it on a phone for testing only (not for the Play Store).
- Release AAB: Actions run > Artifacts > `norvane-release-aab` (kept 30 days). Upload it to the Play Console.

## Good habits
- Protect `main` and `develop` in GitHub (Settings > Branches): require pull requests and passing CI.
- In Settings > Environments, open `release` and add yourself as a required reviewer so nobody can build a signed
  AAB without approval.
- Pin third-party actions to a commit SHA once you are comfortable (they are tag-pinned now).
