#!/usr/bin/env bash
#
# Build the dashboard and assemble the whole site in .build/site/.
#
#   scripts/assemble.sh
#
# The site is ONE static export: the dashboard shell, which holds every agent's screens as code-split chunks, plus the
# static files of public/agents/<id>/ (images, samples ...) that Next copies to out/agents/<id>/. There are no per-agent builds.
#
# What it does, in order:
#   1. Manifests: infra/render.py --check-manifests validates agents/<id>/manifest.json for every id in infra/agents.txt,
#              before the long build starts (a typo there should not cost a build).
#   2. Build:  `npm run build` in frontend-msp (a static export into out/, plus out/.msp-build.json with the SHA-256 of
#              every inline script). out/ is deleted first, so a stale export can never be deployed.
#   3. Assemble: out/ is copied (hard-linked, the disk is small; nothing in out/ is modified) to .build/site/, without the
#              build metadata (.msp-build.json), NOTES.md and .DS_Store.
#   4. Check:  infra/render.py --check-site: renders the template and the two CloudFront Functions into .build/ and checks
#              the site (every inline <script> has its hash declared, no source maps or credentials, only known agent
#              folders, no file under an API proxy prefix ...).
#
# Fails loudly (non-zero, with the reason) when any piece is missing or does not pass. Nothing here touches AWS.
#
# Knobs (environment): SKIP_BUILD=1 reuses out/ (assemble and check only);
#   SHELL_BUILD_CMD (default "npm run build"; scripts/locked-build.sh takes turns with other builds on a busy machine);
#   MSP_ROOT (a different frontend-msp folder, used by the tests).
# Needs: bash, python3, node, rsync (and npm unless SKIP_BUILD=1).

set -Eeuo pipefail

ROOT="${MSP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BUILD="$ROOT/.build"
SITE="$BUILD/site"
SKIP_BUILD="${SKIP_BUILD:-0}"
SHELL_BUILD_CMD="${SHELL_BUILD_CMD:-npm run build}"

log() { printf '[assemble %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

for tool in python3 node rsync; do command -v "$tool" >/dev/null 2>&1 || die "required command not found: $tool"; done
[ "$SKIP_BUILD" = "1" ] || command -v npm >/dev/null 2>&1 || die "required command not found: npm"
[ -f "$ROOT/infra/agents.txt" ] || die "infra/agents.txt is missing"

log "checking agents/<id>/manifest.json ..."
python3 "$ROOT/infra/render.py" --root "$ROOT" --check-manifests >&2 || die "a manifest does not pass the checks above; nothing was built"

if [ "$SKIP_BUILD" != "1" ]; then
  rm -rf "$BUILD/site" "$BUILD/logs" "$ROOT/out"
  mkdir -p "$BUILD/logs"
  log "building the dashboard (the shell and every agent's screens) ..."
  started=$SECONDS
  if ( cd "$ROOT" && eval "$SHELL_BUILD_CMD" ) >"$BUILD/logs/shell.log" 2>&1; then
    log "  built in $((SECONDS - started))s"
  else
    log "  the build FAILED (last lines of .build/logs/shell.log):"
    tail -n 25 "$BUILD/logs/shell.log" | sed 's/^/    | /' >&2
    die "not assembled: the dashboard build failed (log in .build/logs/shell.log)"
  fi
else
  log "SKIP_BUILD=1: reusing out/"
fi

# The build must have left its pieces, whether it was just run or reused.
MISSING=0
for needed in "$ROOT/out/index.html" "$ROOT/out/.msp-build.json"; do
  [ -f "$needed" ] || { log "missing: ${needed#"$ROOT"/}"; MISSING=1; }
done
[ "$MISSING" = "0" ] || die "not assembled: the dashboard build left no complete out/ (logs in .build/logs/)"

log "assembling $SITE ..."
rm -rf "$SITE"
mkdir -p "$SITE"
rsync -a --exclude '.msp-build.json' --exclude 'NOTES.md' --exclude '.DS_Store' --link-dest="$ROOT/out/" "$ROOT/out/" "$SITE/"

log "checking the declarations and the site ..."
python3 "$ROOT/infra/render.py" --root "$ROOT" --check-site "$SITE" >&2 || die "the manifests or the site do not pass the checks above; nothing was deployed"

log "done: $(find "$SITE" -type f | wc -l | tr -d ' ') files, $(du -sh "$SITE" | cut -f1) in .build/site"
log "next: scripts/deploy.sh (a dry run; APPLY=1 scripts/deploy.sh applies it). To look at it in a browser first: node infra/emulate.mjs"
