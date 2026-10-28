#!/usr/bin/env bash
# Turns this folder into a git repository with the git-flow branches (main + develop) and adds the OpenVPN engine.
# Usage: bash scripts/init-repo.sh [--no-engine]
set -euo pipefail
cd "$(dirname "$0")/.."
ENGINE=1; [ "${1:-}" = "--no-engine" ] && ENGINE=0
die() { echo "[problem] $*" >&2; exit 1; }
command -v git >/dev/null || die "git is not installed (Windows: https://git-scm.com/download/win)."
[ -d backend ] && [ -d android ] || die "Run this from the project folder that contains backend/ and android/."
git config user.name >/dev/null && git config user.email >/dev/null || die "Tell git who you are first:
  git config --global user.name  \"Your Name\"
  git config --global user.email \"you@example.com\""

if [ ! -d .git ]; then git init -b main >/dev/null; fi
git add -A
git diff --cached --quiet || git commit -q -m "Initial commit: backend + Android app + CI"

if [ "$ENGINE" -eq 1 ]; then
  echo "Adding the OpenVPN engine (needs internet)..."
  ./android/scripts/setup-openvpn-engine.sh
  git add -A
  git diff --cached --quiet || git commit -q -m "Add OpenVPN engine submodule"
else
  echo "Skipping the OpenVPN engine. Debug APKs will use the stub engine and cannot connect."
fi

git show-ref --verify --quiet refs/heads/develop || git branch develop
git checkout -q develop
cat <<DONE

Repository ready. Branches: main (releases) and develop (daily work). You are on 'develop'.
Next:
  1. Create an EMPTY PRIVATE repository on github.com (no README), then:
       git remote add origin https://github.com/YOU/REPO.git
       git push -u origin main develop
  2. Add the secrets: see docs/SIGNING.md
  3. Open the "Actions" tab: every push builds a debug APK. Tag vX.Y.Z to build the signed AAB.
DONE
