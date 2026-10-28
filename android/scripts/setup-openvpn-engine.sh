#!/usr/bin/env bash
# Adds the ics-openvpn engine (GPL-2.0, see README "Licensing") as a git submodule at android/ics-openvpn.
# Run INSIDE the git repository (scripts/init-repo.sh at the project root creates it and calls this).
# Needs: git. To build locally also: Android NDK + CMake (SDK Manager) and SWIG (apt/brew install swig).
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Not inside a git repository. Run scripts/init-repo.sh from the project root first." >&2; exit 1; }
if [ ! -f "$ROOT/android/ics-openvpn/main/build.gradle" ] && [ ! -f "$ROOT/android/ics-openvpn/main/build.gradle.kts" ]; then
  git -C "$ROOT" submodule add https://github.com/schwabe/ics-openvpn.git android/ics-openvpn
fi
git -C "$ROOT" submodule update --init --recursive
echo "Done. Pin it to a release tag you reviewed:  (cd android/ics-openvpn && git tag --list | tail)"
echo "Then commit the submodule: git add android/ics-openvpn .gitmodules && git commit -m 'Add OpenVPN engine'"
