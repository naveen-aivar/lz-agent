#!/usr/bin/env bash
#
# Tests for scripts/assemble.sh and scripts/deploy.sh, with no AWS access and no network:
#   - assemble.sh runs on a scratch copy with a fake dashboard build (infra/fixtures/fake_build.py) and the fixture manifests,
#   - deploy.sh runs against a test double of the AWS CLI (infra/fixtures/stubs/aws, with aws_direct.py for S3 and CloudFront)
#     that only records its calls and keeps a pretend account, in both deploy modes (cfn: CloudFormation; direct: infra/direct.py),
#   - the smoke checks run against infra/emulate.mjs, which serves the assembled site through the generated
#     CloudFront Functions on port 5470 (make sure nothing else uses it).
#
#   bash infra/test_scripts.sh        (needs bash, python3, node, rsync, curl, and the aws CLI for `s3 cp --dryrun`)
#
# Everything it creates lives in a temporary folder that is removed on exit, also when a test fails.

set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=5470
WORK="$(mktemp -d "${TMPDIR:-/tmp}/msp-script-test.XXXXXX")"
EMULATOR_PID=""
PASSED=0
FAILED=0

stop_emulator() { if [ -n "$EMULATOR_PID" ]; then kill "$EMULATOR_PID" 2>/dev/null || true; wait "$EMULATOR_PID" 2>/dev/null || true; EMULATOR_PID=""; fi; }
cleanup() { stop_emulator; rm -rf "$WORK"; }
trap cleanup EXIT

check() { # description, then a command that must succeed
  local description="$1"; shift
  if "$@" >/dev/null 2>&1; then PASSED=$((PASSED + 1)); printf '  ok    %s\n' "$description"
  else FAILED=$((FAILED + 1)); printf '  FAIL  %s\n' "$description"; fi
}
has() { grep -qF -- "$2" "$1"; }          # file contains the text
lacks() { ! grep -qF -- "$2" "$1"; }      # file does not contain the text
fails() { ! "$@"; }
no_call() { ! grep -qE -- "$1" "$WORK/stub.log"; }   # the AWS CLI double was never called like this (extended regular expression)

if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; then echo "port $PORT is in use; stop what runs there first" >&2; exit 2; fi
REAL_AWS="$(command -v aws)" || { echo "the aws CLI is needed for the dry-run file counts" >&2; exit 2; }
export REAL_AWS

new_root() { # name -> a scratch copy of the tooling with the fixture manifests as agents/<id>/manifest.json, in $WORK/<name>
  local dir="$WORK/$1" id
  mkdir -p "$dir"
  rsync -a --exclude __pycache__ --exclude .build "$SRC/infra" "$SRC/scripts" "$dir/"
  cp "$SRC/infra/fixtures/agents.txt" "$dir/infra/agents.txt"   # the fixture agents, not the dashboard's (empty) list
  for id in $(ls "$SRC/infra/fixtures/agents"); do   # every fixture agent (test_render.py's TestAgentList keeps them equal to infra/fixtures/agents.txt)
    mkdir -p "$dir/agents/$id"
    cp "$SRC/infra/fixtures/agents/$id/manifest.json" "$dir/agents/$id/manifest.json"
  done
  printf '%s' "$dir"
}
assemble() { # root, extra env as args: runs assemble.sh, output in $WORK/assemble.out
  local root="$1"; shift
  ( cd "$root" && env MSP_ROOT="$root" SHELL_BUILD_CMD="python3 infra/fixtures/fake_build.py out" "$@" bash scripts/assemble.sh ) > "$WORK/assemble.out" 2>&1
}
start_emulator() { # root
  stop_emulator
  node "$1/infra/emulate.mjs" --root "$1" --port "$PORT" > "$WORK/emulator.log" 2>&1 &
  EMULATOR_PID=$!
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/" && return 0
    sleep 0.25
  done
  echo "the emulator did not start:"; cat "$WORK/emulator.log"; exit 2
}
deploy() { # root, state dir, extra env: runs deploy.sh (DEPLOY_MODE=cfn unless the extra env says otherwise) against the stub; output in $WORK/deploy.out, calls in $WORK/stub.log
  local root="$1" state="$2"; shift 2
  mkdir -p "$state"
  ( cd "$root" && env MSP_ROOT="$root" PATH="$SRC/infra/fixtures/stubs:$PATH" STUB_LOG="$WORK/stub.log" STUB_STATE="$state" \
      AWS_PROFILE=stub-profile DEPLOY_MODE=cfn DOMAIN_NAME=mm.aivar.app "$@" bash scripts/deploy.sh ) > "$WORK/deploy.out" 2>&1
}
mutating_calls() { grep -E '^(cloudformation deploy|s3 sync|s3 cp [^|]*|cloudfront create-invalidation|s3api (create|put)|cloudfront (create|update|publish))' "$WORK/stub.log" | grep -v -- '--dryrun' || true; }

echo "assemble.sh"
ROOT1="$(new_root main)"
check "builds the dashboard and assembles the site from out/ alone (no agents/<id>/build.sh exists)" assemble "$ROOT1"
SITE="$ROOT1/.build/site"
check "the dashboard is at the root and each agent's static files under agents/<id>/" test -f "$SITE/index.html" -a -f "$SITE/_next/static/chunks/app-0123456789abcdef.js" -a -f "$SITE/agents/devops/images/logo.png" -a -f "$SITE/agents/sre/img/topology.svg"
check "an agent with no static files has no folder (wafr and backupdr have none)" test ! -e "$SITE/agents/wafr" -a ! -e "$SITE/agents/backupdr"
check "no .msp-build.json or NOTES.md leaks into the site" fails sh -c "find '$SITE' -name .msp-build.json -o -name NOTES.md | grep -q ."
check "the template and both functions are rendered" test -s "$ROOT1/.build/template.json" -a -s "$ROOT1/.build/router.js" -a -s "$ROOT1/.build/headers.js" -a -s "$ROOT1/.build/smoke.txt"
check "  ... the headers function holds the one policy (frame-ancestors 'none', the dashboard's hashes)" sh -c "grep -q \"frame-ancestors 'none'\" '$ROOT1/.build/headers.js' && grep -q 'sha256-' '$ROOT1/.build/headers.js'"
check "there are no per-agent builds" test ! -e "$ROOT1/.build/agents"
check "assembling again from the same out/ works (SKIP_BUILD=1)" assemble "$ROOT1" SKIP_BUILD=1

ROOT2="$(new_root missing-manifest)"; rm "$ROOT2/agents/wafr/manifest.json"
check "a missing manifest fails loudly, naming the agent" fails assemble "$ROOT2"
check "  ... and says which" has "$WORK/assemble.out" "agents/wafr/manifest.json: file not found"
check "  ... before anything was built" test ! -e "$ROOT2/out"

ROOT2B="$(new_root bad-manifest)"; sed -i.bak 's#"originDomain": "[^"]*"#"originDomain": "https://x.example.com"#' "$ROOT2B/agents/secops/manifest.json"
check "an invalid manifest fails loudly" fails assemble "$ROOT2B"
check "  ... naming the file and the field" has "$WORK/assemble.out" "agents/secops/manifest.json.apiProxy[0].originDomain"
check "  ... before anything was built" test ! -e "$ROOT2B/out"

ROOT2C="$(new_root unlisted-manifest)"; mkdir -p "$ROOT2C/agents/surprise"; cp "$ROOT2C/agents/sre/manifest.json" "$ROOT2C/agents/surprise/manifest.json"
check "a manifest of an agent that is not in infra/agents.txt fails" fails assemble "$ROOT2C"
check "  ... saying so" has "$WORK/assemble.out" "this agent is not in infra/agents.txt"

ROOT3="$(new_root failing-build)"
check "a failing dashboard build fails loudly" fails env MSP_ROOT="$ROOT3" SHELL_BUILD_CMD='echo "compile error in sre module"; exit 3' bash -c "cd '$ROOT3' && bash scripts/assemble.sh > '$WORK/assemble.out' 2>&1"
check "  ... shows the end of its log and says the build failed" sh -c "grep -q 'compile error in sre module' '$WORK/assemble.out' && grep -q 'not assembled: the dashboard build failed' '$WORK/assemble.out'"

ROOT4="$(new_root no-shell)"
check "a build that makes no out/ fails loudly" fails env MSP_ROOT="$ROOT4" SHELL_BUILD_CMD="true" bash -c "cd '$ROOT4' && bash scripts/assemble.sh > '$WORK/assemble.out' 2>&1"
check "  ... naming out/index.html" has "$WORK/assemble.out" "missing: out/index.html"

ROOT5="$(new_root bad-hash)"; assemble "$ROOT5" >/dev/null 2>&1
printf '<script>alert(1)</script>' >> "$ROOT5/out/index.html"
check "an inline script nobody declared stops the assembly" fails assemble "$ROOT5" SKIP_BUILD=1
check "  ... naming the page" has "$WORK/assemble.out" "index.html: inline script 'sha256-"
ROOT5B="$(new_root stray-files)"; assemble "$ROOT5B" >/dev/null 2>&1
mkdir -p "$ROOT5B/out/agents/devops/api" "$ROOT5B/out/agents/old-agent"; echo '{}' > "$ROOT5B/out/agents/devops/api/sample.json"; echo x > "$ROOT5B/out/agents/old-agent/index.html"
check "a static file under an API prefix and a folder of an unknown agent stop the assembly" fails assemble "$ROOT5B" SKIP_BUILD=1
check "  ... naming both" sh -c "grep -q 'agents/devops/api/sample.json: is under an API proxy prefix' '$WORK/assemble.out' && grep -q 'site/agents/old-agent: is not a known agent' '$WORK/assemble.out'"

echo "deploy.sh dry run (the AWS CLI is a test double)"
check "a dry run succeeds" deploy "$ROOT1" "$WORK/state-dry"
check "  ... says it is a dry run and changed nothing" has "$WORK/deploy.out" "DRY RUN finished: nothing was changed"
check "  ... plans the stack as CREATED" has "$WORK/deploy.out" "does not exist, would be CREATED"
check "  ... counts the three cache classes (2 + 5 + 4 = 11 files)" sh -c "grep -q '2 hashed assets' '$WORK/deploy.out' && grep -q '5 other files' '$WORK/deploy.out' && grep -q '4 html/json/txt' '$WORK/deploy.out'"
check "  ... made no call that changes AWS" test -z "$(mutating_calls)"
: > "$WORK/stub.log"
check "the wrong AWS account is refused" fails deploy "$ROOT1" "$WORK/state-dry" STUB_ACCOUNT=111111111111
check "  ... saying why" has "$WORK/deploy.out" "only for 455162169375"
check "  ... before anything else was asked of AWS" test "$(wc -l < "$WORK/stub.log" | tr -d ' ')" = 1

echo "deploy.sh APPLY=1 (DEPLOY_MODE=cfn), first deploy (smoke checks run against the emulator)"
start_emulator "$ROOT1"
STATE="$WORK/state"; : > "$WORK/stub.log"
check "the first deploy succeeds" deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... the stack is deployed with the Project tag" has "$WORK/stub.log" "Project=ingram-mm-dashboard"
check "  ... the account is checked first" sh -c "head -n 1 '$WORK/stub.log' | grep -q 'sts get-caller-identity'"
check "  ... the stack is deployed before any upload" sh -c "[ \$(grep -n 'cloudformation deploy' '$WORK/stub.log' | head -n 1 | cut -d: -f1) -lt \$(grep -n '^s3 sync' '$WORK/stub.log' | head -n 1 | cut -d: -f1) ]"
check "  ... hashed assets first (sync), other files next, HTML last" sh -c "grep -nE '^s3 (sync|cp)' '$WORK/stub.log' | grep -v -- '--dryrun' | sed -E 's/^[0-9]+://' | awk '{print \$2, (\$0 ~ /immutable/ ? \"immutable\" : (\$0 ~ /no-cache/ ? \"no-cache\" : \"1h\"))}' | tr '\n' ',' | grep -q '^sync immutable,cp 1h,cp no-cache,\$'"
check "  ... never --delete" fails grep -q -- '--delete' "$WORK/stub.log"
check "  ... invalidates /* and waits" sh -c "grep -q 'create-invalidation' '$WORK/stub.log' && grep -q 'cloudfront wait invalidation-completed' '$WORK/stub.log'"
check "  ... the bucket was empty, so no backup was made" fails test -d "$ROOT1/.build/backup"
check "  ... no smoke check failed" lacks "$WORK/deploy.out" "FAIL"
check "  ... the dashboard answers with its CSP (frame-ancestors 'none', the first script hash) and X-Frame-Options DENY" has "$WORK/deploy.out" "ok    shell /: 200, html, CSP with frame-ancestors 'none' and its script hash, security headers"
check "  ... a deep link is the dashboard too" has "$WORK/deploy.out" "ok    shell route /overview/some-deep-link: 200"
check "  ... a missing file is a 404, not the dashboard" has "$WORK/deploy.out" "a missing file is an error (404), not the dashboard page"
check "  ... the hashed JS is immutable" sh -c "grep -q 'ok    shell asset /_next/static/chunks/app-0123456789abcdef.js: 200, javascript, cache-control immutable' '$WORK/deploy.out'"
check "  ... an agent's static file is served as that file, and a missing one under /agents/<id>/ is a 404" has "$WORK/deploy.out" "ok    agent sre static file /agents/sre/img/topology.svg: 200, image/svg+xml"
check "  ... an agent without static files is skipped, not failed" sh -c "grep -qF 'skip  agent wafr: the site has no static files under /agents/wafr/' '$WORK/deploy.out' && grep -qF 'skip  agent backupdr: the site has no static files under /agents/backupdr/' '$WORK/deploy.out'"
check "  ... no frame, embed or per-agent page is checked any more" sh -c "! grep -qE 'msp-embed|no trailing slash|agent [a-z]+ /agents/[a-z]+/ ' '$WORK/deploy.out'"
check "  ... API paths were probed (information only), also one whose origin path is the root" sh -c "grep -qF 'info  API /agents/secops/api/ answered HTTP 200' '$WORK/deploy.out' && grep -qF 'info  API /agents/backupdr/api/ answered HTTP 200' '$WORK/deploy.out'"
check "  ... the DNS record to create is printed" sh -c "grep -Eq 'mm.aivar.app +CNAME +dstub123.cloudfront.net' '$WORK/deploy.out'"
check "deploy.sh never passes the delete flag to S3" fails sh -c "grep -v '^ *#' '$SRC/scripts/deploy.sh' | grep -q -- '--delete'"

echo "the cache classes deploy.sh uploads are the ones the emulator (and so the smoke checks) expect"
python3 - "$WORK/stub.log" "$SITE" > "$WORK/classes.txt" <<'PY'
import os, shlex, subprocess, sys
log, site = sys.argv[1:3]
env = dict(os.environ, AWS_ACCESS_KEY_ID="stub", AWS_SECRET_ACCESS_KEY="stub", AWS_DEFAULT_REGION="us-east-1")
env.pop("AWS_PROFILE", None)
for line in open(log):
    args = shlex.split(line)
    if args[:2] not in (["s3", "sync"], ["s3", "cp"]) or "--dryrun" in args or not args[2].startswith("/"):
        continue
    cache = args[args.index("--cache-control") + 1]
    filters = [a for i, a in enumerate(args) if a in ("--include", "--exclude") or args[i - 1] in ("--include", "--exclude")]
    out = subprocess.run([os.environ["REAL_AWS"], "s3", "cp", site, "s3://placeholder", "--recursive", "--dryrun", *filters], capture_output=True, text=True, env=env).stdout
    for row in out.splitlines():
        print(cache, row.split(" to s3://placeholder/")[1])
PY
check "  ... all 11 files fall in exactly one class" test "$(wc -l < "$WORK/classes.txt" | tr -d ' ')" = 11
check "  ... only the hashed _next/static files are immutable (the agents' static files keep their names)" sh -c "[ \"\$(grep -c '^public,max-age=31536000,immutable ' '$WORK/classes.txt')\" = 2 ] && ! grep '^public,max-age=31536000,immutable ' '$WORK/classes.txt' | grep -v ' _next/static/'"
MISMATCH=0
while read -r cache key; do
  got="$(curl -s -o /dev/null -D - "http://127.0.0.1:$PORT/$key" | tr -d '\r' | awk 'tolower($1)=="cache-control:" {print $2}')"
  if [ "$got" != "$cache" ]; then MISMATCH=$((MISMATCH + 1)); echo "    $key: uploaded as $cache, emulator serves $got"; fi
done < "$WORK/classes.txt"
check "  ... and the emulator serves each file with that same Cache-Control" test "$MISMATCH" = 0

echo "deploy.sh APPLY=1 (DEPLOY_MODE=cfn), second deploy and rollback"
: > "$WORK/stub.log"
check "a re-deploy succeeds" deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
BACKUP="$(find "$ROOT1/.build/backup" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sed -n '1p' || true)"
check "  ... the live bucket was backed up first" test -n "$BACKUP" -a "$(find "$BACKUP" -type f | wc -l | tr -d ' ')" = 11
check "  ... before the first overwrite" sh -c "[ \$(grep -n '^s3 sync s3://stub-bucket' '$WORK/stub.log' | head -n 1 | cut -d: -f1) -lt \$(grep -n 'cache-control' '$WORK/stub.log' | grep -v -- '--dryrun' | head -n 1 | cut -d: -f1) ]"
check "  ... the plan said the stack would be UPDATED and unchanged" sh -c "grep -q 'would be UPDATED' '$WORK/deploy.out' && grep -q 'none (template and parameters are the same)' '$WORK/deploy.out'"
: > "$WORK/stub.log"
check "a rollback from the backup succeeds" deploy "$ROOT1" "$STATE" APPLY=1 ROLLBACK_FROM="$BACKUP" SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... leaves the stack alone" lacks "$WORK/stub.log" "cloudformation deploy"
check "  ... uploads with the right cache headers again" sh -c "grep -q 'immutable' '$WORK/stub.log' && grep -q 'no-cache' '$WORK/stub.log'"
check "  ... and does not print the DNS record again" lacks "$WORK/deploy.out" "CNAME"
check "ROLLBACK_FROM with something that is not a backup is refused" fails deploy "$ROOT1" "$STATE" APPLY=1 ROLLBACK_FROM="$ROOT1/infra"

echo "smoke checks catch a broken deployment"
ROOT6="$WORK/broken"; cp -R "$ROOT1" "$ROOT6"
python3 - "$ROOT6/.build/headers.js" <<'PY'
import re, sys
path = sys.argv[1]
code = open(path).read()
# the policy loses every script hash, as if the wrong policy had been published
code = re.sub(r"(script-src 'self')[^;]*;", r"\1;", code)
open(path, "w").write(code)
PY
start_emulator "$ROOT6"
check "a page served with the wrong policy fails the deploy" fails deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... naming the page and the reason" has "$WORK/deploy.out" "shell / CSP does not carry the page's script hash"
check "  ... and telling how to go back" has "$WORK/deploy.out" "ROLLBACK_FROM=.build/backup/"
sed -i.bak "s/frame-ancestors 'none'/frame-ancestors 'self'/" "$ROOT6/.build/headers.js"
start_emulator "$ROOT6"
check "a policy that lets the same origin frame the dashboard fails the deploy" fails deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... naming it" has "$WORK/deploy.out" "CSP has no frame-ancestors 'none'"
cp "$ROOT1/.build/headers.js" "$ROOT6/.build/headers.js"
rm "$ROOT6/.build/site/_next/static/chunks/app-0123456789abcdef.js"
start_emulator "$ROOT6"
check "a file the page refers to that is missing fails the deploy" fails deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... naming it" has "$WORK/deploy.out" "refers to /_next/static/chunks/app-0123456789abcdef.js, which answered HTTP 404"
cp -R "$ROOT1/.build/site/_next" "$ROOT6/.build/site/"   # put it back; now a router that no longer leaves /agents/<id>/ files alone
python3 - "$ROOT6/.build/router.js" <<'PY'
import sys
path = sys.argv[1]
code = open(path).read()
code = code.replace("if (uri.indexOf('/agents/') === 0 && uri.length > 8) {", "if (false) {").replace("return uri.substring(uri.lastIndexOf('/') + 1).indexOf('.') !== -1;", "return false;")
open(path, "w").write(code)
PY
start_emulator "$ROOT6"
check "an agent's static file that comes back as the dashboard page fails the deploy" fails deploy "$ROOT1" "$STATE" APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... naming it" has "$WORK/deploy.out" "static file /agents/devops/images/logo.png came back as HTML"
stop_emulator

echo "deploy.sh DEPLOY_MODE=direct (infra/direct.py against the pretend S3 and CloudFront)"
ROOT7="$(new_root direct)"; assemble "$ROOT7" >/dev/null 2>&1
DSTATE="$WORK/state-direct"; : > "$WORK/stub.log"
check "a dry run in direct mode succeeds" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct
check "  ... plans every resource as new" sh -c "grep -c 'would create' '$WORK/deploy.out' | grep -q '^7$'"
check "  ... made no call that changes AWS" test -z "$(mutating_calls)"
check "  ... and never used CloudFormation" no_call '^cloudformation'
start_emulator "$ROOT7"; : > "$WORK/stub.log"
check "the first direct deploy succeeds" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... created the bucket, both functions and the distribution" sh -c "grep -q '^s3api create-bucket --bucket ingram-mm-dashboard-455162169375-us-east-1' '$WORK/stub.log' && grep -q '^cloudfront create-function --name ingram-mm-dashboard-router' '$WORK/stub.log' && grep -q '^cloudfront create-function --name ingram-mm-dashboard-headers' '$WORK/stub.log' && grep -q '^cloudfront create-distribution-with-tags' '$WORK/stub.log'"
check "  ... never used CloudFormation" no_call '^cloudformation'
check "  ... uploaded after the resources were there" sh -c "[ \$(grep -n 'create-distribution-with-tags' '$WORK/stub.log' | head -n 1 | cut -d: -f1) -lt \$(grep -n '^s3 sync' '$WORK/stub.log' | head -n 1 | cut -d: -f1) ]"
check "  ... every smoke check passed" sh -c "! grep -q 'FAIL' '$WORK/deploy.out' && grep -q 'ok    shell /' '$WORK/deploy.out' && grep -q 'ok    agent devops static file' '$WORK/deploy.out'"
check "  ... the DNS record to create names the new distribution" sh -c "grep -Eq 'mm.aivar.app +CNAME +ddirect1.cloudfront.net' '$WORK/deploy.out'"
check "  ... the headers policy sent is the new shape (X-Frame-Options DENY)" sh -c "python3 -c \"import json,sys; d=json.load(open('$DSTATE/direct.json')); sys.exit(0 if d['headers_policies']['HP-STUB']['SecurityHeadersConfig']['FrameOptions']['FrameOption']=='DENY' else 1)\""

: > "$WORK/stub.log"
check "a second direct deploy of the same site succeeds" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... creates and updates nothing (the lists CloudFront returns in its own order are not differences)" no_call '^(s3api create-bucket|cloudfront (create-(function|origin|response|distribution)|update-|publish-))'
check "  ... and its plan said everything was up to date (5 resources compared with what is live)" sh -c "grep -c 'up to date' '$WORK/deploy.out' | grep -q '^5$' && ! grep -q 'would update' '$WORK/deploy.out'"

echo "  the shape change on a site that already runs the old shape"
python3 - "$DSTATE/direct.json" <<'PY'
import json, sys
path = sys.argv[1]
state = json.load(open(path))
state["headers_policies"]["HP-STUB"]["SecurityHeadersConfig"]["FrameOptions"]["FrameOption"] = "SAMEORIGIN"   # what runs today
for name in ("ingram-mm-dashboard-router", "ingram-mm-dashboard-headers"):
    state["functions"][name]["live"] = "// the old per-agent function\nfunction handler(event) { return event.request; }\n"
    state["functions"][name]["dev"] = state["functions"][name]["live"]
json.dump(state, open(path, "w"))
PY
: > "$WORK/stub.log"
check "a direct dry run over the old shape says what would change" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct
check "  ... both functions and the response headers policy would be updated" sh -c "grep -q 'would update .*CloudFront function ingram-mm-dashboard-router' '$WORK/deploy.out' && grep -q 'would update .*CloudFront function ingram-mm-dashboard-headers' '$WORK/deploy.out' && grep -q 'would update .*response headers policy' '$WORK/deploy.out'"
check "  ... the request policy and the distribution are up to date" sh -c "grep -q 'up to date .*origin request policy' '$WORK/deploy.out' && grep -q 'up to date .*CloudFront distribution' '$WORK/deploy.out'"
check "  ... and nothing was written" test -z "$(mutating_calls)"
: > "$WORK/stub.log"
check "a direct deploy over the old shape succeeds" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... updates and publishes both functions and the headers policy" sh -c "grep -q '^cloudfront update-function --name ingram-mm-dashboard-router' '$WORK/stub.log' && grep -q '^cloudfront update-function --name ingram-mm-dashboard-headers' '$WORK/stub.log' && grep -q '^cloudfront publish-function --name ingram-mm-dashboard-router' '$WORK/stub.log' && grep -q '^cloudfront publish-function --name ingram-mm-dashboard-headers' '$WORK/stub.log' && grep -q '^cloudfront update-response-headers-policy' '$WORK/stub.log'"
check "  ... leaves the distribution and the origin request policy alone (same behaviours)" no_call '^cloudfront (update-distribution|create-distribution|update-origin-request-policy)'
check "  ... X-Frame-Options is DENY now" sh -c "python3 -c \"import json,sys; d=json.load(open('$DSTATE/direct.json')); sys.exit(0 if d['headers_policies']['HP-STUB']['SecurityHeadersConfig']['FrameOptions']['FrameOption']=='DENY' else 1)\""
check "  ... the live functions are the new code" sh -c "python3 -c \"import json,sys; d=json.load(open('$DSTATE/direct.json')); sys.exit(0 if 'frame-ancestors' in d['functions']['ingram-mm-dashboard-headers']['live'] and 'CONFIG.api' in d['functions']['ingram-mm-dashboard-router']['live'] else 1)\""

echo "  a new external host changes only the headers function"
python3 - "$ROOT7/agents/sre/manifest.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["externalHosts"]["img-src"].append("https://images.example.com")
json.dump(data, open(path, "w"))
PY
check "the site is assembled again with it" assemble "$ROOT7" SKIP_BUILD=1
start_emulator "$ROOT7"; : > "$WORK/stub.log"
check "the direct deploy succeeds" deploy "$ROOT7" "$DSTATE" DEPLOY_MODE=direct APPLY=1 SMOKE_BASE_URL="http://127.0.0.1:$PORT"
check "  ... updates and publishes the headers function only" sh -c "grep -q '^cloudfront update-function --name ingram-mm-dashboard-headers' '$WORK/stub.log' && grep -q '^cloudfront publish-function --name ingram-mm-dashboard-headers' '$WORK/stub.log' && ! grep -qE '^cloudfront (update|publish)-function --name ingram-mm-dashboard-router' '$WORK/stub.log'"
check "  ... and the new policy carries the host" sh -c "python3 -c \"import json,sys; d=json.load(open('$DSTATE/direct.json')); sys.exit(0 if 'https://images.example.com' in d['functions']['ingram-mm-dashboard-headers']['live'] else 1)\""
check "  ... without touching the distribution or the policies" no_call '^cloudfront (update-distribution|update-response-headers-policy|update-origin-request-policy)'
stop_emulator

echo
echo "$PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ]
