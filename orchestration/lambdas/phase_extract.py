"""Deterministic SOW text extraction. Combines the typed requirements and the uploaded file into runs/<id>/sow.txt.
Fails loudly (never truncates) so the agent always reads the complete document."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from common import ARTIFACT_BUCKET, audit, get_run, record_artifact, s3
from lzcore.extract import MAX_CHARS, extract

MIN_CHARS = 100


def handler(event, _ctx):
    run_id = event["runId"]
    run = get_run(run_id)
    parts = []
    typed = (run.get("requirements") or "").strip()
    if typed:
        parts.append("=== Requirements text (typed by requester) ===\n" + typed)
    key = run.get("inputKey")
    if key:
        body = s3().get_object(Bucket=ARTIFACT_BUCKET, Key=key)["Body"].read()
        parts.append(f"=== Uploaded file: {run.get('inputName', key)} ===\n" + extract(body, key.rsplit(".", 1)[-1]))
    full = "\n\n".join(parts)
    if len(full.strip()) < MIN_CHARS:
        raise ValueError(f"input too short ({len(full.strip())} chars); provide the SOW or fuller requirements")
    if len(full) > MAX_CHARS:
        raise ValueError(f"input is {len(full)} chars, above the {MAX_CHARS} limit; split the SOW or remove appendices")
    out_key = f"runs/{run_id}/sow.txt"
    s3().put_object(Bucket=ARTIFACT_BUCKET, Key=out_key, Body=full.encode(), ServerSideEncryption="aws:kms")
    sha = record_artifact(run_id, "sow", out_key)
    audit(run_id, "system", "sow.extracted", {"chars": len(full), "sha": sha, "file": run.get("inputName")})
    return {"runId": run_id}
