#!/usr/bin/env bash
# `next build` for this folder, one build at a time across everyone working on the dashboard on this machine (each build needs about 1.5 GB of
# memory and the disk is small), then the .next folder is removed. Output: ./out
#   scripts/locked-build.sh
set -Eeuo pipefail
LOCK="${TMPDIR:-/tmp}/msp-build.lock"
while ! mkdir "$LOCK" 2>/dev/null; do
  if [ -f "$LOCK/pid" ] && ! kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  echo "[locked-build] another build is running, waiting ..." >&2; sleep 10
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
cd "$(dirname "${BASH_SOURCE[0]}")/.."
rm -rf .next
NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=3072}" npm run build
rm -rf .next
