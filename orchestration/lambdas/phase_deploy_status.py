"""Terminal status for deploy runs (contract C11).

Two callers:
  - deployment.asl.json MarkDelivered / MarkFailed: {"runId", "status": "DELIVERED" | "FAILED", "error"?}.
  - EventBridge rule DeployExecutionEndedRule (infra/platform/platform.yaml): the "Step Functions Execution
    Status Change" event for the deploy state machine with detail.status TIMED_OUT, ABORTED or FAILED. The run
    id is the execution name (api_runs._deploy names the execution after the deploy run). This covers the
    paths that never reach MarkFailed: the 72 h execution timeout, a console/API abort, and MarkDelivered or
    MarkFailed failing after their retries. The run is marked FAILED.

Idempotent: the status write is conditional on META.status = RUNNING, so it never flips DELIVERED to FAILED (or
back). A run that is already DELIVERED or FAILED (by /stop, by the other caller, or by an earlier attempt of this
one) only gets its stored deploy-target keys re-checked and deleted, with no second deploy.<status> audit. A
terminal signal that disagrees with the recorded status (e.g. the execution FAILED after MarkDelivered recorded
DELIVERED, because the key delete kept failing) is audited once as deploy.terminal_status_kept.

On the first terminal write the pending Transform question is cleared. A key-deletion failure is recorded
(META.credentialsCleanupError + audit) and raised, so the task fails visibly and is retried.
"""
from __future__ import annotations

import json
import os

from botocore.exceptions import ClientError

from common import audit, delete_run_credentials, get_run, table

TERMINAL = ("DELIVERED", "FAILED")
EXECUTION_EVENT_DETAIL_TYPE = "Step Functions Execution Status Change"
EXECUTION_END_STATUSES = ("TIMED_OUT", "ABORTED", "FAILED")


class ExecutionEventRejected(ValueError):
    """The EventBridge event is not a deploy-execution end this handler owns."""


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


def _from_execution_event(event: dict) -> tuple[str, str, dict]:
    """(run id, failure cause, audit detail) for a deploy-execution status-change event."""
    if event.get("source") != "aws.states":
        raise ExecutionEventRejected(f"expected source aws.states, got {event.get('source')!r}")
    detail = event.get("detail")
    if not isinstance(detail, dict):
        raise ExecutionEventRejected("execution status event has no detail object")
    status = detail.get("status")
    if status not in EXECUTION_END_STATUSES:
        raise ExecutionEventRejected(
            f"execution status {status!r} is not one of {EXECUTION_END_STATUSES}; the EventBridge rule pattern "
            "must match only terminal failure statuses"
        )
    expected = os.environ.get("DEPLOY_STATE_MACHINE_ARN", "").strip()
    if not expected:
        raise RuntimeError(
            "DEPLOY_STATE_MACHINE_ARN is not set on the phase-deploy Lambda; redeploy infra/platform/platform.yaml "
            "from this revision"
        )
    if detail.get("stateMachineArn") != expected:
        raise ExecutionEventRejected(
            f"execution belongs to {detail.get('stateMachineArn')!r}, not the deploy state machine {expected}"
        )
    run_id = detail.get("name")
    if not isinstance(run_id, str) or not run_id:
        raise ExecutionEventRejected("execution status event has no execution name (the deploy run id)")
    error = detail.get("error") or "no error reported"
    reason = _error_cause({"Cause": detail.get("cause")}) or "no cause reported"
    cause = f"Deploy execution ended {status} ({error}: {reason})"[:1500]
    return run_id, cause, {
        "source": "eventbridge",
        "executionStatus": status,
        "executionArn": detail.get("executionArn"),
    }


def _recheck(run: dict, requested: str, extra: dict) -> dict:
    """Already terminal: re-check key cleanup only. No second deploy.<status> audit."""
    current = run["status"]
    if requested != current:
        audit(run["runId"], "system", "deploy.terminal_status_kept",
              {"status": current, "requestedStatus": requested, **extra})
    delete_run_credentials(run, "system", recheck=True)
    return {"runId": run["runId"], "status": current, "alreadyTerminal": True}


def handler(event, _ctx):
    if event.get("detail-type") == EXECUTION_EVENT_DETAIL_TYPE:
        run_id, cause, extra = _from_execution_event(event)
        status = "FAILED"
    else:
        run_id, status = event["runId"], event["status"]
        if status not in TERMINAL:
            raise ValueError(f"phase_deploy_status: status must be one of {TERMINAL}, got {status!r}")
        cause, extra = _error_cause(event.get("error")), {}

    run = get_run(run_id)
    if not run:
        raise RuntimeError(f"deploy run {run_id} META not found while marking it {status}")
    if run.get("runKind") != "deploy":
        raise RuntimeError(f"run {run_id} is not a deploy run (runKind={run.get('runKind')!r})")
    if run.get("status") in TERMINAL:
        return _recheck(run, status, extra)
    if run.get("status") != "RUNNING":
        raise RuntimeError(f"deploy run {run_id} is {run.get('status')!r}; only a RUNNING run can become {status}")

    try:
        table().update_item(
            Key={"PK": f"RUN#{run_id}", "SK": "META"},
            UpdateExpression="SET #s = :s, #e = :e, awaitingHitl = :no REMOVE pendingHumanInput",
            ConditionExpression="#s = :running",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": status, ":e": cause, ":no": False, ":running": "RUNNING"},
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        # Another terminal writer (/stop, the other caller) won the race since the read above.
        run = get_run(run_id)
        if not run or run.get("status") not in TERMINAL:
            raise RuntimeError(
                f"deploy run {run_id}: conditional {status} write failed but the run is "
                f"{(run or {}).get('status')!r}, not terminal"
            ) from e
        return _recheck(run, status, extra)

    detail = {"error": cause} if cause else {}
    audit(run_id, "system", f"deploy.{status.lower()}", {**detail, **extra})
    delete_run_credentials(run, "system")
    return {"runId": run_id, "status": status}
