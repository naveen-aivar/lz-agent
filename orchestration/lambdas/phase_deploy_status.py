"""Mark deploy runs DELIVERED or FAILED (deployment.asl.json MarkDelivered / MarkFailed).

Both are terminal: the pending Transform question is cleared and stored deploy-target keys are deleted.
A deletion failure is recorded (META.credentialsCleanupError + audit) and raised, so the execution fails visibly.
"""
import json

from common import audit, delete_run_credentials, get_run, table

TERMINAL = ("DELIVERED", "FAILED")


def _error_cause(err) -> str:
    if not err:
        return ""
    if isinstance(err, str):
        return err[:1500]
    cause = err.get("Cause") or err.get("errorMessage") or err.get("Error") or ""
    if isinstance(cause, dict):
        return str(cause.get("errorMessage") or cause)[:1500]
    try:
        parsed = json.loads(cause)
        if isinstance(parsed, dict):
            msg = parsed.get("errorMessage") or parsed.get("error")
            if msg:
                return str(msg)[:1500]
    except (ValueError, TypeError, AttributeError):
        pass
    return str(cause)[:1500]


def handler(event, _ctx):
    run_id, status = event["runId"], event["status"]
    if status not in TERMINAL:
        raise ValueError(f"phase_deploy_status: status must be one of {TERMINAL}, got {status!r}")
    cause = _error_cause(event.get("error"))

    table().update_item(
        Key={"PK": f"RUN#{run_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, #e = :e, awaitingHitl = :no REMOVE pendingHumanInput",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": status, ":e": cause, ":no": False},
    )
    audit(run_id, "system", f"deploy.{status.lower()}", {"error": cause} if cause else {})
    run = get_run(run_id)
    if not run:
        raise RuntimeError(f"deploy run {run_id} META disappeared while marking it {status}")
    delete_run_credentials(run, "system")
    return {"runId": run_id, "status": status}
