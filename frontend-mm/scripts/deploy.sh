#!/usr/bin/env bash
#
# Deploy the Migration and Modernization dashboard (one static site: the shell, every agent's screens and the agents' static files) to AWS:
# one S3 bucket behind one CloudFront distribution, with each agent's API proxied under /agents/<id>/api/.
#
#   scripts/deploy.sh                 DRY RUN: checks everything, prints the plan, changes nothing in AWS
#   APPLY=1 scripts/deploy.sh         does it
#   ROLLBACK_FROM=.build/backup/<time> APPLY=1 scripts/deploy.sh      puts an earlier backup back (see infra/README.md)
#
# Run scripts/assemble.sh first: it builds the dashboard and leaves .build/site/ plus the rendered template.
#
# What APPLY=1 does, in order (it stops at the first failure):
#   1. account guard: refuses to run unless the AWS account is 455162169375 (also in a dry run)
#   2. the AWS resources: DEPLOY_MODE=direct (the default) creates or updates them with S3 and CloudFront API calls (infra/direct.py, from the same
#        rendered template); DEPLOY_MODE=cfn runs aws cloudformation deploy of .build/template.json as stack ingram-mm-dashboard
#   3. backup of the live bucket to .build/backup/<UTC time>/ (re-deploys only; before the first overwrite)
#   4. upload, and never with --delete (files of earlier deploys stay in the bucket):
#        hashed assets first (_next/static: cache 1 year, immutable), then other files (1 hour),
#        HTML/JSON/TXT last (no-cache), so a page never points at an asset that is not there yet
#   5. CloudFront invalidation /* and wait for it
#   6. smoke checks through the distribution: the dashboard page and a deep link answer 200 with the Content-Security-Policy
#        and the security headers, the files the page references load, a missing file is a 404, each agent's static files
#        are served as files (not as the dashboard page) and each API proxy path answers
#   7. prints the DNS record to create by hand (aivar.app is not hosted in this account)
#
# Settings (environment): APPLY (0|1), DEPLOY_MODE (direct|cfn), AWS_PROFILE (default arun-doc-ex), STACK_NAME (default ingram-mm-dashboard),
#   DOMAIN_NAME (default empty: the cloudfront.net name only; e.g. mm.aivar.app with the *.aivar.app CERTIFICATE_ARN), CERTIFICATE_ARN (the *.aivar.app one),
#   ROLLBACK_FROM (a backup folder), SMOKE_BASE_URL (check this URL instead of the distribution; for the emulator).
# Needs: aws (v2), python3, node, curl.

set -Eeuo pipefail

ROOT="${MSP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BUILD="$ROOT/.build"
EXPECTED_ACCOUNT="455162169375"
REGION="us-east-1"
STACK_NAME="${STACK_NAME:-ingram-mm-dashboard}"
PROJECT_TAG="ingram-mm-dashboard"
DOMAIN_NAME="${DOMAIN_NAME-}"
CERTIFICATE_ARN="${CERTIFICATE_ARN-arn:aws:acm:us-east-1:455162169375:certificate/df4a2cb0-96be-4c56-9639-fad4dd000d8d}"
APPLY="${APPLY:-0}"
# direct: create/update the S3 bucket and CloudFront resources with API calls (infra/direct.py); for a login that may not use CloudFormation.
# cfn: one CloudFormation stack (needs a login that may use CloudFormation).
DEPLOY_MODE="${DEPLOY_MODE:-direct}"
ROLLBACK_FROM="${ROLLBACK_FROM:-}"
SMOKE_BASE_URL="${SMOKE_BASE_URL:-}"
export AWS_PROFILE="${AWS_PROFILE:-arun-doc-ex}" AWS_DEFAULT_REGION="$REGION" AWS_REGION="$REGION" AWS_PAGER=""

# Which cache header each file gets. One definition, used for the dry-run count and for the upload.
# Only Next's content-hashed files are immutable; the agents' static files (public/agents/<id>/) keep their names, so they are not.
IMMUTABLE_FILTERS=(--exclude '*' --include '_next/static/*')
REVALIDATE_FILTERS=(--exclude '*' --include '*.html' --include '*.json' --include '*.txt' --exclude '_next/static/*')
OTHER_FILTERS=(--exclude '*.html' --exclude '*.json' --exclude '*.txt' --exclude '_next/static/*')
CACHE_IMMUTABLE="public,max-age=31536000,immutable"
CACHE_OTHER="public,max-age=3600"
CACHE_REVALIDATE="no-cache"

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

case "${1:-}" in
  -h|--help) sed -n '2,/^set -Eeuo/p' "${BASH_SOURCE[0]}" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 0 ;;
  '') ;;
  *) die "unknown argument: $1 (settings are environment variables; see --help)" ;;
esac

TMP="$(mktemp -d "${TMPDIR:-/tmp}/msp-deploy.XXXXXX")"
CHANGED_AWS=0
BACKUP_DIR=""
on_exit() {
  local status=$?
  rm -rf "$TMP"
  if [ "$status" -ne 0 ] && [ "$CHANGED_AWS" = "1" ]; then
    log "STOPPED after changes to AWS began. Some of the site may be new and some old."
    if [ -n "$BACKUP_DIR" ]; then
      log "The live site before this run is saved in ${BACKUP_DIR#"$ROOT"/}. To put it back: ROLLBACK_FROM=${BACKUP_DIR#"$ROOT"/} APPLY=1 scripts/deploy.sh"
    fi
    log "Running this script again is safe: it repeats the same steps."
  fi
}
trap on_exit EXIT

for tool in aws python3 node curl; do command -v "$tool" >/dev/null 2>&1 || die "required command not found: $tool"; done

# ---- 1. which account? -----------------------------------------------------------------------------------------
IDENTITY="$(aws sts get-caller-identity --query '[Account,Arn]' --output text 2>&1)" \
  || die "cannot call AWS with profile $AWS_PROFILE: $IDENTITY (try: aws sso login --profile $AWS_PROFILE)"
ACCOUNT="$(printf '%s' "$IDENTITY" | awk '{print $1}')"
[ "$ACCOUNT" = "$EXPECTED_ACCOUNT" ] || die "signed in to account $ACCOUNT, but this deploy is only for $EXPECTED_ACCOUNT (profile $AWS_PROFILE)"
log "account $ACCOUNT, region $REGION, profile $AWS_PROFILE"
if [ "$APPLY" = "1" ]; then log "APPLY=1: this run changes AWS."; else log "DRY RUN: nothing will be changed (APPLY=1 applies)."; fi

# ---- 2. what is deployed: the site folder and the template -----------------------------------------------------
mkdir -p "$BUILD"
if [ -n "$ROLLBACK_FROM" ]; then
  [ -d "$ROLLBACK_FROM" ] || die "ROLLBACK_FROM=$ROLLBACK_FROM is not a folder"
  SITE_DIR="$(cd "$ROLLBACK_FROM" && pwd)"
  [ -f "$SITE_DIR/index.html" ] || die "$SITE_DIR has no index.html: that is not a backup of this site"
  log "ROLLBACK: the site comes from $SITE_DIR; the stack and the template are left alone."
else
  SITE_DIR="$BUILD/site"
  [ -f "$SITE_DIR/index.html" ] || die "$SITE_DIR is not there: run scripts/assemble.sh first"
  log "re-checking the builds and the site (infra/render.py) ..."
  python3 "$ROOT/infra/render.py" --root "$ROOT" --check-site "$SITE_DIR" --quiet >&2 \
    || die "the builds or the site do not pass the checks above (nothing was changed in AWS)"
  if [ "$DEPLOY_MODE" = "cfn" ]; then
    aws cloudformation validate-template --template-body "file://$BUILD/template.json" >/dev/null \
      || die "CloudFormation rejects .build/template.json"
    log "template ok: $(wc -c < "$BUILD/template.json" | tr -d ' ') bytes, accepted by CloudFormation validate-template"
  else
    log "template ok: $(wc -c < "$BUILD/template.json" | tr -d ' ') bytes (rendered; deployed directly, not through CloudFormation)"
  fi
fi

# ---- 3. the stack ----------------------------------------------------------------------------------------------
case "$DEPLOY_MODE" in direct|cfn) ;; *) die "DEPLOY_MODE must be direct or cfn" ;; esac
direct() { DOMAIN_NAME="$DOMAIN_NAME" CERTIFICATE_ARN="$CERTIFICATE_ARN" python3 "$ROOT/infra/direct.py" "$@" --root "$ROOT"; }
STACK_STATUS="NONE"
if [ "$DEPLOY_MODE" = "direct" ]; then
  state="$(direct status)" || die "cannot read what exists in AWS (see the message above; nothing was changed)"
  if [ "$state" = "EXISTS" ]; then STACK_STATUS="UPDATE_COMPLETE"; fi
elif described="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].StackStatus' --output text 2>&1)"; then
  STACK_STATUS="$described"
else
  case "$described" in
    *"does not exist"*) STACK_STATUS="NONE" ;;
    *) die "cannot read stack $STACK_NAME: $described" ;;
  esac
fi
case "$STACK_STATUS" in
  NONE|CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE|IMPORT_COMPLETE) ;;
  *) die "stack $STACK_NAME is in state $STACK_STATUS, which a deploy cannot continue from. Look at: aws cloudformation describe-stack-events --stack-name $STACK_NAME (a ROLLBACK_COMPLETE or empty REVIEW_IN_PROGRESS stack must be deleted first, by you)" ;;
esac
if [ -n "$ROLLBACK_FROM" ] && [ "$STACK_STATUS" = "NONE" ]; then die "ROLLBACK_FROM needs the stack $STACK_NAME to exist"; fi

stack_output() { aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
BUCKET=""; DIST_ID=""; DIST_DOMAIN=""
read_outputs() {
  if [ "$DEPLOY_MODE" = "direct" ]; then
    local found
    found="$(direct outputs)" || die "the bucket and the distribution are not both there"
    BUCKET="$(printf '%s' "$found" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bucket"])')"
    DIST_ID="$(printf '%s' "$found" | python3 -c 'import json,sys; print(json.load(sys.stdin)["distributionId"])')"
    DIST_DOMAIN="$(printf '%s' "$found" | python3 -c 'import json,sys; print(json.load(sys.stdin)["distributionDomain"])')"
  else
    BUCKET="$(stack_output SiteBucketName)"; DIST_ID="$(stack_output DistributionId)"; DIST_DOMAIN="$(stack_output DistributionDomainName)"
  fi
  if [ -z "$BUCKET" ] || [ "$BUCKET" = "None" ] || [ -z "$DIST_ID" ] || [ "$DIST_ID" = "None" ]; then die "stack $STACK_NAME has no bucket/distribution outputs"; fi
}

# What a re-deploy would change in the stack (read-only): resources whose definition differs, parameters that differ.
show_template_diff() {
  aws cloudformation get-template --stack-name "$STACK_NAME" --template-stage Original --query TemplateBody --output json > "$TMP/deployed-template.json"
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].Parameters' --output json > "$TMP/deployed-parameters.json"
  python3 - "$TMP/deployed-template.json" "$BUILD/template.json" "$TMP/deployed-parameters.json" "$DOMAIN_NAME" "$CERTIFICATE_ARN" <<'PY'
import json, sys
deployed_path, new_path, params_path, domain, certificate = sys.argv[1:6]
deployed = json.load(open(deployed_path))
if isinstance(deployed, str):
    deployed = json.loads(deployed)
new = json.load(open(new_path))
old_r, new_r = deployed.get("Resources", {}), new["Resources"]
lines = []
for name in sorted(set(old_r) | set(new_r)):
    if name not in old_r:
        lines.append(f"  + {name} (new)")
    elif name not in new_r:
        lines.append(f"  - {name} (would be REMOVED)")
    elif old_r[name] != new_r[name]:
        a, b = old_r[name].get("Properties", {}), new_r[name].get("Properties", {})
        keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        lines.append(f"  ~ {name}: {', '.join(keys) or 'attributes'} changed")
current = {p["ParameterKey"]: p.get("ParameterValue") for p in json.load(open(params_path)) or []}
for key, want in (("DomainName", domain), ("CertificateArn", certificate)):
    if current.get(key) != want:
        lines.append(f"  ~ parameter {key}: {current.get(key)!r} -> {want!r}")
print("stack changes if applied:" if lines else "stack changes if applied: none (template and parameters are the same)")
print("\n".join(lines))
PY
}

# ---- 4. the plan -----------------------------------------------------------------------------------------------
count_group() { # prints how many files a group of filters selects; asks S3 nothing (the bucket name is a placeholder)
  aws s3 cp "$SITE_DIR" "s3://dry-run-placeholder" --recursive --dryrun "$@" | grep -c '^(dryrun) upload:' || true
}
TOTAL_FILES="$(find "$SITE_DIR" -type f | wc -l | tr -d ' ')"
N_IMMUTABLE="$(count_group "${IMMUTABLE_FILTERS[@]}")"
N_OTHER="$(count_group "${OTHER_FILTERS[@]}")"
N_REVALIDATE="$(count_group "${REVALIDATE_FILTERS[@]}")"
if [ "$((N_IMMUTABLE + N_OTHER + N_REVALIDATE))" -ne "$TOTAL_FILES" ]; then
  die "cache classes cover $((N_IMMUTABLE + N_OTHER + N_REVALIDATE)) of $TOTAL_FILES files (are there symlinks or odd file names in the site?)"
fi

log "PLAN"
if [ "$DEPLOY_MODE" = "direct" ]; then
  log "  direct (no CloudFormation): each resource below is created if missing, updated if it differs, never deleted"
  direct plan | sed 's/^/    /' >&2 || die "cannot read what exists in AWS"
elif [ "$STACK_STATUS" = "NONE" ]; then
  log "  stack $STACK_NAME: does not exist, would be CREATED (bucket, distribution, two functions, policies; about 5 to 10 minutes)"
elif [ -n "$ROLLBACK_FROM" ]; then
  log "  stack $STACK_NAME: $STACK_STATUS, left alone (rollback)"
else
  log "  stack $STACK_NAME: $STACK_STATUS, would be UPDATED"
  if show_template_diff > "$TMP/template-diff.txt" 2> "$TMP/template-diff.err"; then
    sed 's/^/    /' "$TMP/template-diff.txt" >&2
  else
    log "    (could not compare with the deployed template: $(head -c 300 "$TMP/template-diff.err"))"
  fi
fi
if [ -z "$ROLLBACK_FROM" ]; then
  if [ -n "$DOMAIN_NAME" ]; then log "  custom domain: $DOMAIN_NAME with certificate ${CERTIFICATE_ARN##*/}"; else log "  custom domain: none (the cloudfront.net name only)"; fi
fi
log "  site: $TOTAL_FILES files, $(du -sh "$SITE_DIR" | cut -f1), from ${SITE_DIR#"$ROOT"/}"
log "    $N_IMMUTABLE hashed assets  -> cache-control $CACHE_IMMUTABLE   (uploaded first)"
log "    $N_OTHER other files        -> cache-control $CACHE_OTHER"
log "    $N_REVALIDATE html/json/txt  -> cache-control $CACHE_REVALIDATE   (uploaded last)"
if [ "$STACK_STATUS" != "NONE" ]; then
  read_outputs
  OBJECTS="$(aws s3 ls "s3://$BUCKET" --recursive --summarize 2>/dev/null | awk '/Total Objects:/ {print $3}' || true)"
  log "  bucket $BUCKET holds ${OBJECTS:-0} objects now; they are backed up to .build/backup/<time>/ before anything is overwritten; nothing is ever deleted"
fi
log "  then: invalidate /* and wait, smoke checks, print the DNS record to create"

if [ "$APPLY" != "1" ]; then
  log "DRY RUN finished: nothing was changed. Run again with APPLY=1 to do it."
  exit 0
fi

# ---- 5. apply: stack ---------------------------------------------------------------------------------------------
if [ -z "$ROLLBACK_FROM" ] && [ "$DEPLOY_MODE" = "direct" ]; then
  CHANGED_AWS=1
  log "creating/updating the resources directly (waits until the distribution is deployed) ..."
  direct apply >/dev/null || die "the direct deploy failed (see above). It is safe to run again: it repeats the same steps"
elif [ -z "$ROLLBACK_FROM" ]; then
  CHANGED_AWS=1
  log "deploying the stack (waits until CloudFormation and CloudFront are done) ..."
  aws cloudformation deploy --stack-name "$STACK_NAME" --template-file "$BUILD/template.json" \
    --parameter-overrides "DomainName=$DOMAIN_NAME" "CertificateArn=$CERTIFICATE_ARN" \
    --tags "Project=$PROJECT_TAG" --no-fail-on-empty-changeset >&2 \
    || die "the stack deploy failed. See: aws cloudformation describe-stack-events --stack-name $STACK_NAME --max-items 15"
fi
read_outputs
log "bucket $BUCKET, distribution $DIST_ID ($DIST_DOMAIN)"

# ---- 6. apply: backup of what is live ----------------------------------------------------------------------------
backup_live_site() {
  local summary objects bytes avail_kb need_kb copied
  summary="$(aws s3 ls "s3://$BUCKET" --recursive --summarize 2>/dev/null | tail -n 2 || true)"
  objects="$(printf '%s\n' "$summary" | awk '/Total Objects:/ {print $3}')"
  bytes="$(printf '%s\n' "$summary" | awk '/Total Size:/ {print $3}')"
  if [ "${objects:-0}" -eq 0 ]; then log "the bucket is empty: first publish, nothing to back up"; return 0; fi
  avail_kb="$(df -Pk "$BUILD" | awk 'NR==2 {print $4}')"
  need_kb=$(( ${bytes:-0} / 1024 + 524288 ))
  if [ "$avail_kb" -le "$need_kb" ]; then
    die "not enough free disk for the backup: need about $((need_kb / 1024)) MiB, have $((avail_kb / 1024)) MiB (free some space; nothing in the bucket was touched)"
  fi
  BACKUP_DIR="$BUILD/backup/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$BACKUP_DIR"
  log "backing up the live site ($objects objects, $(( ${bytes:-0} / 1048576 )) MiB) to ${BACKUP_DIR#"$ROOT"/} ..."
  aws s3 sync "s3://$BUCKET" "$BACKUP_DIR" --only-show-errors >&2 || die "the backup failed; nothing in the bucket was touched"
  copied="$(find "$BACKUP_DIR" -type f | wc -l | tr -d ' ')"
  if [ "$copied" -lt "$objects" ]; then log "warning: backed up $copied files for $objects objects (folder markers are not files)"; fi
  log "backup done: $copied files"
}
backup_live_site

# ---- 7. apply: upload (never --delete) -------------------------------------------------------------------------
CHANGED_AWS=1
log "uploading 1/3: hashed assets, immutable for a year ($N_IMMUTABLE files; files already there are skipped) ..."
aws s3 sync "$SITE_DIR" "s3://$BUCKET" "${IMMUTABLE_FILTERS[@]}" --cache-control "$CACHE_IMMUTABLE" --only-show-errors >&2
log "uploading 2/3: other files, one hour ($N_OTHER files) ..."
aws s3 cp "$SITE_DIR" "s3://$BUCKET" --recursive "${OTHER_FILTERS[@]}" --cache-control "$CACHE_OTHER" --only-show-errors >&2
log "uploading 3/3: HTML, JSON, TXT, no-cache, last ($N_REVALIDATE files) ..."
aws s3 cp "$SITE_DIR" "s3://$BUCKET" --recursive "${REVALIDATE_FILTERS[@]}" --cache-control "$CACHE_REVALIDATE" --only-show-errors >&2

# ---- 8. apply: invalidate ----------------------------------------------------------------------------------------
INVALIDATION="$(aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' --query 'Invalidation.Id' --output text)"
log "invalidating the CloudFront cache ($INVALIDATION), waiting ..."
aws cloudfront wait invalidation-completed --distribution-id "$DIST_ID" --id "$INVALIDATION"

# ---- 9. smoke checks ---------------------------------------------------------------------------------------------
BASE_URL="${SMOKE_BASE_URL:-https://$DIST_DOMAIN}"
SMOKE_FAILS=0
F_CODE=000
fail() { log "  FAIL  $*"; SMOKE_FAILS=$((SMOKE_FAILS + 1)); }
pass() { log "  ok    $*"; }

fetch() { # GET $1 (a path) -> F_CODE, headers in $TMP/headers, body in $TMP/body. Retries a few times on 000/5xx.
  local attempt
  for attempt in 1 2 3; do
    F_CODE="$(curl -sS --max-time 30 -o "$TMP/body" -D "$TMP/headers" -w '%{http_code}' "$BASE_URL$1" 2>"$TMP/curl.err")" || F_CODE=000
    case "$F_CODE" in
      000|5??) if [ "$attempt" -lt 3 ]; then sleep 10; fi ;;
      *) return 0 ;;
    esac
  done
  return 0
}
header_value() { # the last value of response header $1, empty if absent
  awk -v want="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" -F': ' 'tolower($1) == want { v = $0; sub(/^[^:]*: */, "", v); sub(/\r$/, "", v); last = v } END { print last }' "$TMP/headers"
}

check_page() { # label, path, expected script hash ("" = none to look for)
  local label="$1" path="$2" hash="$3" ctype csp value problems=0
  fetch "$path"
  if [ "$F_CODE" != "200" ]; then fail "$label $path answered HTTP $F_CODE"; return 0; fi
  ctype="$(header_value content-type)"
  case "$ctype" in text/html*) ;; *) fail "$label $path content-type is '$ctype', not text/html"; problems=1 ;; esac
  csp="$(header_value content-security-policy)"
  if [ -z "$csp" ]; then fail "$label $path has no Content-Security-Policy"; problems=1
  else
    case "$csp" in *"frame-ancestors 'none'"*) ;; *) fail "$label $path CSP has no frame-ancestors 'none'"; problems=1 ;; esac
    case "$csp" in *"script-src 'self'"*) ;; *) fail "$label $path CSP has no script-src 'self'"; problems=1 ;; esac
    case "$csp" in *"script-src 'self' 'unsafe-inline'"*|*"'unsafe-eval'"*) fail "$label $path CSP allows unsafe inline or eval scripts"; problems=1 ;; esac
    if [ -n "$hash" ]; then case "$csp" in *"$hash"*) ;; *) fail "$label $path CSP does not carry the page's script hash: the wrong policy reached this page"; problems=1 ;; esac; fi
  fi
  value="$(header_value x-frame-options)"; if [ "$value" != "DENY" ]; then fail "$label $path X-Frame-Options is '$value', expected DENY"; problems=1; fi
  value="$(header_value x-content-type-options)"; if [ "$value" != "nosniff" ]; then fail "$label $path X-Content-Type-Options is '$value'"; problems=1; fi
  value="$(header_value referrer-policy)"; if [ "$value" != "strict-origin-when-cross-origin" ]; then fail "$label $path Referrer-Policy is '$value'"; problems=1; fi
  value="$(header_value permissions-policy)"; case "$value" in *"camera=()"*"microphone=()"*"geolocation=()"*) ;; *) fail "$label $path Permissions-Policy is '$value'"; problems=1 ;; esac
  case "$BASE_URL" in https://*) value="$(header_value strict-transport-security)"; case "$value" in *max-age=31536000*) ;; *) fail "$label $path Strict-Transport-Security is '$value'"; problems=1 ;; esac ;; esac
  if [ "$problems" = "0" ]; then pass "$label $path: 200, html, CSP with frame-ancestors 'none'${hash:+ and its script hash}, security headers"; fi
  return 0
}

check_references() { # label; the files the page just fetched (in $TMP/body) refers to must load
  local label="$1" refs ref bad=0 count=0
  refs="$(grep -oE '(src|href)="/[^"]+\.(js|css|woff2?|png|jpe?g|svg|ico|webmanifest)"' "$TMP/body" | sed -E 's/^(src|href)="//; s/"$//' | sort -u | sed -n '1,12p' || true)"
  for ref in $refs; do
    count=$((count + 1))
    fetch "$ref"
    if [ "$F_CODE" != "200" ]; then fail "$label refers to $ref, which answered HTTP $F_CODE"; bad=1; fi
  done
  if [ "$bad" = "0" ]; then pass "$label: the $count files it refers to load (200)"; fi
  return 0
}

check_asset() { # label, extension (js|css), type fragment: a hashed file of the build must be served with its type and as immutable
  local label="$1" ext="$2" want="$3" file rel value
  file="$(find "$SITE_DIR" -path '*/_next/static/*' -name "*.$ext" -type f 2>/dev/null | sort | sed -n '1p' || true)"
  if [ -z "$file" ]; then return 0; fi
  rel="/${file#"$SITE_DIR"/}"
  fetch "$rel"
  if [ "$F_CODE" != "200" ]; then fail "$label asset $rel answered HTTP $F_CODE"; return 0; fi
  value="$(header_value content-type)"
  case "$value" in *"$want"*) ;; *) fail "$label asset $rel content-type is '$value', expected $want"; return 0 ;; esac
  value="$(header_value cache-control)"
  case "$value" in *immutable*) pass "$label asset $rel: 200, $want, cache-control immutable" ;; *) fail "$label asset $rel cache-control is '$value', expected immutable" ;; esac
  return 0
}

check_static() { # id; one static file of the agent (public/agents/<id>/) must come back as that file, not as the dashboard page
  local id="$1" dir="$SITE_DIR/agents/$1" file rel value
  file="$(find "$dir" -type f ! -name '*.html' 2>/dev/null | sort | sed -n '1p' || true)"   # an agent without static files has no folder
  if [ -z "$file" ]; then log "  skip  agent $id: the site has no static files under /agents/$id/"; return 0; fi
  rel="/${file#"$SITE_DIR"/}"
  fetch "$rel"
  if [ "$F_CODE" != "200" ]; then fail "agent $id static file $rel answered HTTP $F_CODE"; return 0; fi
  value="$(header_value content-type)"
  case "$value" in text/html*) fail "agent $id static file $rel came back as HTML (the dashboard page?), content-type '$value'"; return 0 ;; esac
  fetch "/agents/$id/missing-file-$$.png"
  case "$F_CODE" in 403|404) pass "agent $id static file $rel: 200, $value; a missing file under /agents/$id/ is an error ($F_CODE), not the dashboard" ;; *) fail "/agents/$id/missing-file-$$.png answered HTTP $F_CODE, expected 404" ;; esac
  return 0
}

log "SMOKE CHECKS against $BASE_URL"
SMOKE_FILE="$BUILD/smoke.txt"
if [ -n "$ROLLBACK_FROM" ] || [ ! -f "$SMOKE_FILE" ]; then
  # A rollback restores an older build: its script hashes are not known here, so only the shell page is checked in full.
  printf 'shell||/|\n' > "$TMP/smoke.txt"
  if [ -f "$SMOKE_FILE" ]; then grep '^agent|' "$SMOKE_FILE" >> "$TMP/smoke.txt" || true; fi
  SMOKE_FILE="$TMP/smoke.txt"
  log "  (rollback: script hashes are not compared)"
fi
while IFS='|' read -r kind id entry hash; do
  case "$kind" in
    shell)
      check_page "shell" "/" "$hash"
      check_references "shell /"
      check_asset "shell" js "javascript"
      check_page "shell route" "/overview/some-deep-link" "$hash"
      fetch "/missing-file-$$.js"
      case "$F_CODE" in 403|404) pass "a missing file is an error ($F_CODE), not the dashboard page" ;; *) fail "/missing-file-$$.js answered HTTP $F_CODE, expected 404" ;; esac
      ;;
    agent)
      check_static "$id"
      ;;
    api)
      # Information only (never a failure): proves the proxy path leaves CloudFront. 502/504 means CloudFront cannot reach the origin.
      fetch "$entry"
      case "$F_CODE" in
        502|504|000) log "  warn  API $entry answered HTTP $F_CODE: CloudFront could not reach the agent's API origin" ;;
        *) log "  info  API $entry answered HTTP $F_CODE (the agent's own API; any answer means the proxy reaches it)" ;;
      esac
      ;;
  esac
done < "$SMOKE_FILE"

if [ "$SMOKE_FAILS" -gt 0 ]; then
  log "SMOKE CHECKS FAILED: $SMOKE_FAILS problem(s). The new site IS live."
  if [ -n "$BACKUP_DIR" ]; then log "To put the previous site back: ROLLBACK_FROM=${BACKUP_DIR#"$ROOT"/} APPLY=1 scripts/deploy.sh"; fi
  exit 1
fi

# ---- 10. done ----------------------------------------------------------------------------------------------------
log "DONE. The dashboard is live at https://$DIST_DOMAIN/"
if [ -n "$BACKUP_DIR" ]; then log "Backup of the previous site: ${BACKUP_DIR#"$ROOT"/} (rollback: ROLLBACK_FROM=${BACKUP_DIR#"$ROOT"/} APPLY=1 scripts/deploy.sh)"; fi
if [ -n "$DOMAIN_NAME" ] && [ -z "$ROLLBACK_FROM" ]; then
  cat >&2 <<EOF

DNS: aivar.app is not hosted in this account, so create this record where the zone is managed:

    $DOMAIN_NAME   CNAME   $DIST_DOMAIN

Until it exists, use https://$DIST_DOMAIN/ . Once it does, https://$DOMAIN_NAME/ works with the *.aivar.app certificate
(check with: dig +short $DOMAIN_NAME CNAME).
EOF
fi
