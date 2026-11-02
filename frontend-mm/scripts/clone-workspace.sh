#!/usr/bin/env bash
# A private copy of the dashboard for one porter to work in, so several people can build and test at once without disturbing each other.
#   scripts/clone-workspace.sh <dest>          e.g. scripts/clone-workspace.sh /tmp/msp/sre
# The copy has the source, the config and a HARD-LINKED node_modules (no extra disk; never run npm install in it: that would change the original).
# Work in <dest>/src/features/<id>/ and <dest>/agents/<id>/. When done, bring those two folders back with:
#   rsync -a --delete <dest>/src/features/<id>/ <original>/src/features/<id>/ && rsync -a <dest>/agents/<id>/ <original>/agents/<id>/
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:?usage: clone-workspace.sh <dest>}"
mkdir -p "$DEST"
rsync -a --exclude node_modules --exclude .next --exclude out --exclude .build --exclude '.DS_Store' "$ROOT/" "$DEST/"
rsync -a --link-dest="$ROOT/node_modules" "$ROOT/node_modules/" "$DEST/node_modules/"
echo "workspace ready: $DEST (node_modules hard-linked; build with: scripts/locked-build.sh)"
