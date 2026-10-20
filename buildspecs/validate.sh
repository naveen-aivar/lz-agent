#!/usr/bin/env bash
# Validates both generated stacks and uploads the scan reports.
# The reports are stored under runs/$RUN_ID/scans/ so the status Lambda can package them into the zip artifacts.
# Exit 1 if any check fails. Reports are uploaded either way.
set -euo pipefail
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
# Skip model-authored JSON, the session transcript, and docs so checkov does not treat them as templates.
SKIP=(--skip-path custom-scps --skip-path session --skip-path docs)
check tf-security terraform checkov -d . --framework terraform --quiet --soft-fail "${SKIP[@]}"
check cfn-lint cloudformation cfn-lint 00-prerequisites.yaml 01-landing-zone.yaml 02-governance.yaml
check cfn-security cloudformation checkov -d . --framework cloudformation --quiet --soft-fail "${SKIP[@]}"

# Full checkov documents, in addition to the pass/fail log above. An export failure does not hide a real check failure.
(cd "$ROOT/src/terraform" && checkov -d . --framework terraform --soft-fail -o json "${SKIP[@]}" > "$ROOT/checkov-terraform.json") || true
(cd "$ROOT/src/cloudformation" && checkov -d . --framework cloudformation --soft-fail -o json "${SKIP[@]}" > "$ROOT/checkov-cloudformation.json") || true

python3 - "$RESULTS" "$ROOT" <<'PY'
import json, pathlib, sys
results, root = sys.argv[1], pathlib.Path(sys.argv[2])
checks = []
for line in open(results):
    name, result = line.rstrip("\n").split("\t")
    log = root / f"{name}.log"
    text = log.read_text(errors="replace") if log.exists() else ""
    checks.append({"name": name, "result": result, "log": f"scans/{name}.log", "excerpt": text[-4000:]})
summary = {"overall": "pass" if all(c["result"] == "pass" for c in checks) else "fail", "checks": checks}
(root / "summary.json").write_text(json.dumps(summary, indent=2))
PY

upload() {
  aws s3 cp "$1" "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/scans/$2" --sse aws:kms --only-show-errors
}
upload "$ROOT/summary.json" summary.json
while IFS=$'\t' read -r name _; do
  upload "$ROOT/$name.log" "$name.log"
done < "$RESULTS"
for extra in checkov-terraform.json checkov-cloudformation.json; do
  if [ -s "$ROOT/$extra" ]; then
    upload "$ROOT/$extra" "$extra"
  fi
done
aws s3 cp "$ROOT/summary.json" "s3://$ARTIFACT_BUCKET/runs/$RUN_ID/validation-report.json" --sse aws:kms --only-show-errors
exit $FAILED
