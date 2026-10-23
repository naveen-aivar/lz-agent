"""Mark deploy runs DELIVERED or FAILED."""
import json

from common import audit, table


def _error_cause(err) -> str:
    if not err:
        return ""
    if isinstance(err, str):
        return err[:500]
    cause = err.get("Cause") or err.get("errorMessage") or err.get("Error") or ""
    if isinstance(cause, dict):
        return str(cause.get("errorMessage") or cause)[:500]
    try:
        parsed = json.loads(cause)
        if isinstance(parsed, dict):
            msg = parsed.get("errorMessage") or parsed.get("error")
            if msg:
                return str(msg)[:500]
    except (ValueError, TypeError, AttributeError):
        pass
    return str(cause)[:500]


def handler(event, _ctx):
    run_id, status = event["runId"], event["status"]
    cause = _error_cause(event.get("error"))

    table().update_item(
        Key={"PK": f"RUN#{run_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": status, ":e": cause},
    )
    audit(run_id, "system", f"deploy.{status.lower()}", {"error": cause} if cause else {})
    return {"runId": run_id, "status": status}
