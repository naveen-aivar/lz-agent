"""Marks the run DELIVERED or FAILED. Downloads of the stacks are only allowed once DELIVERED (i.e. validated).

On the way out, code-scan reports uploaded by CodeBuild are copied into both zip bundles so the
downloadable artifacts contain the scanner output, not only the generated stacks.
"""
import json

from common import ARTIFACT_BUCKET, audit, record_artifact, s3, table
from lzcore import render


def _cause(err):
    if not err:
        return ""
    cause = err.get("Cause", "")
    try:  # Lambda errors arrive as JSON in Cause; CodeBuild failures as a Build document
        parsed = json.loads(cause)
        build = parsed.get("Build")
        if build:
            bad = next((p for p in build.get("Phases", []) if p.get("PhaseStatus") == "FAILED"), {})
            msg = (bad.get("Contexts") or [{}])[0].get("Message", "")
            cause = f"Validation build failed in {bad.get('PhaseType', 'unknown')} phase: {msg}".strip()
        else:
            cause = parsed.get("errorMessage", cause)
    except (ValueError, AttributeError):
        pass
    return str(cause)[:500]


def _objects(prefix):
    """Map of key-relative path -> utf-8 text for every object under prefix."""
    files, token = {}, None
    while True:
        kw = {"Bucket": ARTIFACT_BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3().list_objects_v2(**kw)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not key.startswith(prefix):
                continue
            body = s3().get_object(Bucket=ARTIFACT_BUCKET, Key=key)["Body"].read()
            files[key[len(prefix):]] = body.decode("utf-8", "replace")
        if not resp.get("IsTruncated"):
            return files
        token = resp["NextContinuationToken"]


def _repackage(run_id, scans):
    """Rebuild both zips from the rendered sources plus the scan reports. Returns the new shas."""
    base = f"runs/{run_id}"
    shas = {}
    for fmt in ("terraform", "cloudformation"):
        files = _objects(f"{base}/bundle-src/{fmt}/")
        if not files:
            raise RuntimeError(f"no rendered {fmt} sources to package")
        packed = render.with_scans(files, scans)
        zkey = f"{base}/{fmt}.zip"
        s3().put_object(Bucket=ARTIFACT_BUCKET, Key=zkey, Body=render.zip_bytes(packed, fmt), ServerSideEncryption="aws:kms")
        shas[fmt] = record_artifact(run_id, fmt, zkey)
        audit(run_id, "system", "bundle.packaged", {"format": fmt, "scans": len(scans), "sha": shas[fmt]})
    return shas


def handler(event, _ctx):
    run_id, status = event["runId"], event["status"]
    cause = _cause(event.get("error"))
    scans = _objects(f"runs/{run_id}/scans/")
    if status == "DELIVERED" and not scans:
        raise RuntimeError("validation passed but no code-scan reports were uploaded")
    if scans:
        try:
            _repackage(run_id, scans)
        except Exception as e:
            if status == "DELIVERED":
                raise
            cause = f"{cause} (scan packaging failed: {e})"[:500]
    report_key = f"runs/{run_id}/validation-report.json"
    try:
        record_artifact(run_id, "report", report_key)
    except Exception:
        if status == "DELIVERED":
            raise RuntimeError("validation report is missing")
    table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET #s = :s, #e = :e",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={":s": status, ":e": cause})
    audit(run_id, "system", f"run.{status.lower()}", {"error": cause} if cause else {})
    return {"runId": run_id, "status": status}
