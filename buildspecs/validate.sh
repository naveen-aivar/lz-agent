#!/usr/bin/env bash
# Validates both generated stacks, writes the validation report and the scan-report bundles, uploads them. Exit 1 if any check fails.
# Env: RUN_ID, ARTIFACT_BUCKET. For a local dry run set LOCAL_SRC (a rendered bundle) and LOCAL_OUT instead of using S3.
set -uo pipefail
: "${RUN_ID:?}"
ROOT=$(mktemp -d); SRC="$ROOT/src"; REP="$ROOT/reports"; OUT="${LOCAL_OUT:-$ROOT/out}"; mkdir -p "$REP" "$OUT"
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -n "${LOCAL_SRC:-}" ]; then
  cp -R "$LOCAL_SRC" "$SRC" || exit 1
else
  : "${ARTIFACT_BUCKET:?}"
  aws s3 sync "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/bundle-src/" "$SRC/" --only-show-errors || exit 1
fi
RESULTS="$ROOT/results.tsv"; : > "$RESULTS"; FAILED=0
(cd "$SRC" && find . -type f | sed 's|^\./||' | sort > "$ROOT/files.txt")  # the bundle as rendered, before any tool adds files

# check <name> <dir> <command...>: runs in the stack directory, keeps the full log, records pass/fail
check() {
  local name=$1 dir=$2; shift 2
  if (cd "$SRC/$dir" && "$@") > "$REP/$name.log" 2>&1; then
    printf '%s\tpass\n' "$name" >> "$RESULTS"
  else
    printf '%s\tfail\n' "$name" >> "$RESULTS"; FAILED=1
    echo "=== $name FAILED"; tail -40 "$REP/$name.log"
  fi
}
# json-producing variants: the tool's JSON goes to the report file, its exit code decides pass/fail
check_json() {  # check_json <name> <dir> <report-file> <command...>
  local name=$1 dir=$2 out=$3; shift 3
  if (cd "$SRC/$dir" && "$@" > "$REP/$out" 2> "$REP/$name.log"); then
    printf '%s\tpass\n' "$name" >> "$RESULTS"
  else
    printf '%s\tfail\n' "$name" >> "$RESULTS"; FAILED=1
    echo "=== $name FAILED"; tail -40 "$REP/$out" "$REP/$name.log" 2>/dev/null | head -80
  fi
}

# fmt covers *.tf only; terraform.tfvars is generated.
check tf-fmt terraform bash -c 'terraform fmt -check -diff *.tf'
cp "$REP/tf-fmt.log" "$REP/terraform-fmt.log"
check tf-init terraform terraform init -backend=false -input=false
check_json tf-validate terraform terraform-validate.json terraform validate -json
check_json tf-lint terraform tflint.json tflint --format json
# Security scans are report-only (--soft-fail): the findings are counted in the report, they do not fail the build.
check_json tf-security terraform checkov-terraform.json checkov -d . --framework terraform -o json --soft-fail
check_json cfn-lint cloudformation cfn-lint.json cfn-lint -f json 00-prerequisites.yaml 01-landing-zone.yaml 02-governance.yaml
check_json cfn-security cloudformation checkov-cloudformation.json checkov -d . --framework cloudformation -o json --soft-fail

python3 "$HERE/report.py" "$REP" "$RESULTS" "$SRC" "$OUT" "$RUN_ID" "$ROOT/files.txt" || FAILED=1
if [ -z "${LOCAL_SRC:-}" ]; then
  P="s3://$ARTIFACT_BUCKET/runs/$RUN_ID"
  for f in validation-report.json validation-reports.zip; do aws s3 cp "$OUT/$f" "$P/$f" --sse aws:kms --only-show-errors || FAILED=1; done
  if [ "$FAILED" = 0 ]; then  # the stack bundles are replaced by versions that carry their scan reports
    for f in terraform.zip cloudformation.zip; do aws s3 cp "$OUT/$f" "$P/$f" --sse aws:kms --only-show-errors || FAILED=1; done
  fi
fi
exit $FAILED
