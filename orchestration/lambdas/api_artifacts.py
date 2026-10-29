"""GET /runs/{runId}/artifacts/{name} -> 5-minute presigned download.
name: terraform | cloudformation (only once the run is DELIVERED, i.e. rendered and validated) | report (the JSON summary,
also returned inline) | reports (zip of every raw scan report) | deployment-report (deploy run foundation attestation) |
iac-change-plan | iac-manifest | foundation-assessment (deploy run brownfield/greenfield assessment)."""
import json

from common import ARTIFACT_BUCKET, artifact, audit, envelope_response, get_run, s3

NAMES = {
    "terraform",
    "cloudformation",
    "report",
    "reports",
    "deployment-report",
    "iac-change-plan",
    "iac-manifest",
    "foundation-assessment",
}


def _resp(code, body):
    return envelope_response(code, body)


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
    deploy_json = {"deployment-report", "iac-change-plan", "iac-manifest", "foundation-assessment"}
    if name in deploy_json and run.get("status") != "DELIVERED":
        return _resp(409, {"error": f"{name} is available once the deploy run has finished"})
    art = artifact(run, name)
    if not art:
        return _resp(404, {"error": "artifact not available"})
    if name == "report" and (event.get("queryStringParameters") or {}).get("summary"):  # UI refresh: content only, not a download
        return _resp(200, {"report": json.loads(s3().get_object(Bucket=ARTIFACT_BUCKET, Key=art["key"])["Body"].read()), "sha256": art["sha"]})
    json_names = {"report", "deployment-report", "iac-change-plan", "iac-manifest", "foundation-assessment"}
    filename = f"{run.get('orgSlug', 'landing-zone')}-landing-zone-{name}.{'json' if name in json_names else 'zip'}"
    url = s3().generate_presigned_url(
        "get_object", ExpiresIn=300,
        Params={"Bucket": ARTIFACT_BUCKET, "Key": art["key"], "ResponseContentDisposition": f'attachment; filename="{filename}"'})
    audit(run_id, sub, "artifact.downloaded", {"name": name, "sha": art["sha"]})
    out = {"url": url, "sha256": art["sha"], "filename": filename}
    if name in json_names:
        body = json.loads(s3().get_object(Bucket=ARTIFACT_BUCKET, Key=art["key"])["Body"].read())
        key_map = {
            "report": "report",
            "deployment-report": "deploymentReport",
            "iac-change-plan": "iacChangePlan",
            "iac-manifest": "iacManifest",
            "foundation-assessment": "foundationAssessment",
        }
        out[key_map[name]] = body
    return _resp(200, out)
