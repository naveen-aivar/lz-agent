"""Deterministic stack generation from the saved scope. No LLM. Both formats, fixed layout."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from common import ARTIFACT_BUCKET, audit, get_run, record_artifact, s3, table
from lzcore import render, scope as scopelib


def _get(key):
    return s3().get_object(Bucket=ARTIFACT_BUCKET, Key=key)["Body"].read().decode()


def handler(event, _ctx):
    run_id = event["runId"]
    run = get_run(run_id)
    intake = run["artifacts"]["intake"]
    scope, errors = scopelib.validate(json.loads(_get(intake["key"])), _get(run["artifacts"]["sow"]["key"]))
    if errors:  # defense in depth: the saved scope must still validate
        raise ValueError("saved scope no longer validates: " + "; ".join(errors[:5]))

    slug = scope["customer"]["orgSlug"]
    base = f"runs/{run_id}"
    for fmt, files in render.render_all(scope).items():
        for name, content in files.items():
            s3().put_object(Bucket=ARTIFACT_BUCKET, Key=f"{base}/bundle-src/{fmt}/{name}", Body=content.encode())
        zkey = f"{base}/{fmt}.zip"
        s3().put_object(Bucket=ARTIFACT_BUCKET, Key=zkey, Body=render.zip_bytes(files, fmt))
        sha = record_artifact(run_id, fmt, zkey)
        audit(run_id, "system", "bundle.rendered", {"format": fmt, "files": len(files), "sha": sha})
    table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET orgSlug = :s",
                        ExpressionAttributeValues={":s": slug})
    return {"runId": run_id}
