"""Marks the run DELIVERED or FAILED. Downloads of the stacks are only allowed once DELIVERED (i.e. validated)."""
import json

from common import audit, record_artifact, table


def handler(event, _ctx):
    run_id, status = event["runId"], event["status"]
    err = event.get("error")
    cause = ""
    if err:
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
        cause = str(cause)[:500]
    for name, key in (("report", "validation-report.json"), ("reports", "validation-reports.zip")):
        try:  # the scan reports exist whenever validation ran, including when it failed
            record_artifact(run_id, name, f"runs/{run_id}/{key}")
        except Exception:
            pass
    if status == "DELIVERED":
        for fmt in ("terraform", "cloudformation"):  # CodeBuild replaced the zips with versions that carry their scan reports
            try:
                record_artifact(run_id, fmt, f"runs/{run_id}/{fmt}.zip")
            except Exception:
                pass
    table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET #s = :s, #e = :e",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={":s": status, ":e": cause})
    audit(run_id, "system", f"run.{status.lower()}", {"error": cause} if cause else {})
    return {"runId": run_id, "status": status}
