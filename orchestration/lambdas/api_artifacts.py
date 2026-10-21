"""GET /runs/{runId}/artifacts/{name} -> 5-minute presigned download.
name: terraform | cloudformation (only once the run is DELIVERED, i.e. rendered and validated) | report (the JSON summary,
also returned inline) | reports (zip of every raw scan report)."""
import json

from common import ARTIFACT_BUCKET, audit, get_run, s3

NAMES = {"terraform", "cloudformation", "report", "reports"}


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, _ctx):
    c = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub = c["sub"]
    run_id, name = event["pathParameters"]["runId"], event["pathParameters"]["name"]
    if name not in NAMES:
        return _resp(400, {"error": "unknown artifact"})
    run = get_run(run_id)
    if not run or run["requester"] != sub:
        return _resp(404, {"error": "not found"})
    if name in ("terraform", "cloudformation") and run.get("status") != "DELIVERED":
        return _resp(409, {"error": "stacks are available once validation has passed"})
    art = run["artifacts"].get(name)
    if not art:
        return _resp(404, {"error": "artifact not available"})
    if name == "report" and (event.get("queryStringParameters") or {}).get("summary"):  # UI refresh: content only, not a download
        return _resp(200, {"report": json.loads(s3().get_object(Bucket=ARTIFACT_BUCKET, Key=art["key"])["Body"].read()), "sha256": art["sha"]})
    filename = f"{run.get('orgSlug', 'landing-zone')}-landing-zone-{name}.{'json' if name == 'report' else 'zip'}"
    url = s3().generate_presigned_url(
        "get_object", ExpiresIn=300,
        Params={"Bucket": ARTIFACT_BUCKET, "Key": art["key"], "ResponseContentDisposition": f'attachment; filename="{filename}"'})
    audit(run_id, sub, "artifact.downloaded", {"name": name, "sha": art["sha"]})
    out = {"url": url, "sha256": art["sha"], "filename": filename}
    if name == "report":  # small: the UI shows the scan counts without a second download
        out["report"] = json.loads(s3().get_object(Bucket=ARTIFACT_BUCKET, Key=art["key"])["Body"].read())
    return _resp(200, out)
