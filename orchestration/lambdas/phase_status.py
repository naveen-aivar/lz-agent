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
    if status == "DELIVERED":
        try:
            record_artifact(run_id, "report", f"runs/{run_id}/validation-report.json")
        except Exception:
            pass
    table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET #s = :s, #e = :e",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={":s": status, ":e": cause})
    audit(run_id, "system", f"run.{status.lower()}", {"error": cause} if cause else {})
    return {"runId": run_id, "status": status}
