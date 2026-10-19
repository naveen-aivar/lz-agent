#!/usr/bin/env bash
# Validates both generated stacks and uploads validation-report.json. Exit 1 if any check fails.
set -uo pipefail
: "${RUN_ID:?}" "${ARTIFACT_BUCKET:?}"
ROOT=$(mktemp -d)
aws s3 sync "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/bundle-src/" "$ROOT/src/" --only-show-errors || exit 1
RESULTS="$ROOT/results.tsv"; : > "$RESULTS"; FAILED=0

# check <name> <dir> <command...>
check() {
  local name=$1 dir=$2; shift 2
  if (cd "$ROOT/src/$dir" && "$@") > "$ROOT/$name.log" 2>&1; then
    printf '%s\tpass\n' "$name" >> "$RESULTS"
  else
    printf '%s\tfail\n' "$name" >> "$RESULTS"; FAILED=1
    echo "=== $name FAILED"; tail -40 "$ROOT/$name.log"
  fi
}

# fmt covers *.tf only; terraform.tfvars is generated.
check tf-fmt terraform bash -c 'terraform fmt -check -diff *.tf'
check tf-init terraform terraform init -backend=false -input=false
check tf-validate terraform terraform validate
check tf-lint terraform tflint
check tf-security terraform checkov -d . --framework terraform --quiet --soft-fail
check cfn-lint cloudformation cfn-lint 00-prerequisites.yaml 01-landing-zone.yaml 02-governance.yaml
check cfn-security cloudformation checkov -d . --framework cloudformation --quiet --soft-fail

python3 - "$RESULTS" "$ROOT/report.json" <<'PY'
import json, sys
checks = [dict(zip(("name", "result"), l.rstrip("\n").split("\t"))) for l in open(sys.argv[1])]
json.dump({"overall": "pass" if all(c["result"] == "pass" for c in checks) else "fail", "checks": checks}, open(sys.argv[2], "w"), indent=2)
PY
aws s3 cp "$ROOT/report.json" "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/validation-report.json" --sse aws:kms --only-show-errors
exit $FAILED
